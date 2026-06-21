import asyncio
import logging
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class PyMOLMCPBridge:
    """
    Persistent async MCP client that wraps the pymol_mcp FastMCP subprocess.
    One subprocess, one session, reused for all uAgent calls.
    """

    def __init__(self):
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()
        self._lock = asyncio.Lock()  # MCP stdio is sequential: one call at a time

    async def start(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "pymol_mcp.server"],
        )
        read, write = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        logger.info("PyMOL MCP bridge initialized")

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool by name. Returns {success, text}."""
        async with self._lock:
            if self._session is None:
                return {"success": False, "text": "Bridge not started"}
            try:
                result = await self._session.call_tool(name, arguments)
                text = ""
                if result.content:
                    text = result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
                return {"success": not result.isError, "text": text}
            except Exception as e:
                logger.error(f"MCP tool call failed [{name}]: {e}")
                return {"success": False, "text": str(e)}

    async def stop(self):
        await self._exit_stack.aclose()
        self._session = None
        logger.info("PyMOL MCP bridge stopped")
