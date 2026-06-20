"""PyMOL MCP Bridge - Expose PyMOL as MCP tools to LLM agents."""

__version__ = "0.1.0"

from .config import PyMOLConfig
from .client import PyMOLClient, get_client
from . import tools

__all__ = [
    "PyMOLConfig",
    "PyMOLClient",
    "get_client",
    "tools",
]
