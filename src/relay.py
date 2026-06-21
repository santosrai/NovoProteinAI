"""Reverse-WebSocket relay for NovoProteinAI.

Why this exists
---------------
The agent is deployed publicly (e.g. Railway) but each user's PyMOL runs on
their own laptop, behind NAT. A cloud service cannot reach `localhost:9877` on a
user's machine. So we reverse the connection: the local PyMOL plugin dials *out*
to this relay over a persistent WebSocket, and the cloud agent pushes JSON-RPC
commands down that socket.

Pairing
-------
Chat arrives via Agentverse (identified by the sender's agent address); PyMOL
arrives via WebSocket (identified by a user-chosen token). They are linked by a
pairing token:

  1. Plugin connects to  wss://<app>/plugin?token=<token>
  2. User sends chat:     "pair <token>"  -> stores sender -> token
  3. Tool calls for that chat session route to the websocket under <token>.

This module exposes a FastAPI `app` (the public surface) plus helpers used by
the agent (`call_plugin`, `set_pairing`, `get_token`).
"""

import asyncio
import json
import logging
from typing import Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

app = FastAPI(title="NovoProteinAI Relay")

# token -> live plugin websocket
_plugins: Dict[str, WebSocket] = {}
# request_id -> Future awaiting the plugin's JSON-RPC reply
_pending: Dict[str, "asyncio.Future"] = {}
# chat sender address -> pairing token
_pairings: Dict[str, str] = {}

# The relay's event loop, captured at startup so the (synchronous) LangGraph
# tools can schedule coroutines onto it via run_coroutine_threadsafe.
_loop: Optional[asyncio.AbstractEventLoop] = None


def get_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return the relay's running event loop (None before startup)."""
    return _loop


@app.on_event("startup")
async def _capture_loop():
    global _loop
    _loop = asyncio.get_running_loop()
    logger.info("Relay event loop captured")


@app.get("/")
async def health():
    """Health/info endpoint (useful for Railway and quick checks)."""
    return {
        "service": "novoproteinai-relay",
        "connected_plugins": list(_plugins.keys()),
        "paired_sessions": len(_pairings),
    }


@app.websocket("/plugin")
async def plugin_socket(ws: WebSocket):
    """Endpoint the local PyMOL plugin connects to.

    Query param `token` identifies the session. The plugin sends JSON-RPC
    *responses* (to commands we pushed) as text frames; we correlate them to
    pending futures by `id`.
    """
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return

    await ws.accept()

    # Replace any stale connection for this token.
    old = _plugins.get(token)
    if old is not None:
        try:
            await old.close()
        except Exception:
            pass
    _plugins[token] = ws
    logger.info("Plugin connected: token=%s", token)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Dropping non-JSON frame from token=%s", token)
                continue

            rid = msg.get("id")
            fut = _pending.pop(rid, None) if rid is not None else None
            if fut is not None and not fut.done():
                fut.set_result(msg)
    except WebSocketDisconnect:
        logger.info("Plugin disconnected: token=%s", token)
    except Exception as exc:  # noqa: BLE001 - keep the relay alive
        logger.warning("Plugin socket error (token=%s): %s", token, exc)
    finally:
        if _plugins.get(token) is ws:
            del _plugins[token]


async def call_plugin(
    token: str, method: str, params: dict, timeout: float = 60.0
) -> dict:
    """Send a JSON-RPC command to the plugin for `token` and await its reply.

    Returns the plugin's JSON-RPC response dict, or a JSON-RPC-style error dict
    if no plugin is connected / it times out. Never raises.
    """
    ws = _plugins.get(token)
    if ws is None:
        return {
            "error": {
                "code": -32300,
                "message": (
                    f"No PyMOL connected for token '{token}'. "
                    "Open the PyMOL plugin, enter this token, and click Connect."
                ),
            }
        }

    rid = uuid4().hex
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _pending[rid] = fut

    request = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    try:
        await ws.send_text(json.dumps(request))
    except Exception as exc:  # connection dropped mid-send
        _pending.pop(rid, None)
        return {"error": {"code": -32300, "message": f"Send failed: {exc}"}}

    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        _pending.pop(rid, None)
        return {
            "error": {
                "code": -32300,
                "message": f"PyMOL did not respond within {timeout:.0f}s.",
            }
        }


def set_pairing(sender: str, token: str) -> None:
    """Associate a chat sender (agent address) with a pairing token."""
    _pairings[sender] = token
    logger.info("Paired sender=%s -> token=%s", sender, token)


def get_token(sender: str) -> Optional[str]:
    """Return the pairing token for a chat sender, if any."""
    return _pairings.get(sender)


def is_plugin_connected(token: Optional[str]) -> bool:
    """True if a plugin websocket is currently registered for `token`."""
    return bool(token) and token in _plugins
