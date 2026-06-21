import asyncio
import logging
import os

import re
import uuid
import datetime
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

from .mcp_bridge import PyMOLMCPBridge
from .protocols import (
    ColorSelectionRequest,
    ColorSelectionResponse,
    LoadStructureRequest,
    LoadStructureResponse,
    PingRequest,
    PingResponse,
    RenderImageRequest,
    RenderImageResponse,
)
from .validators import (
    validate_color,
    validate_dimensions,
    validate_output_path,
    validate_source,
)

logger = logging.getLogger(__name__)

SEED = os.environ.get("PYMOL_AGENT_SEED", "pymol-uagent-default-seed-change-me")
AGENTVERSE_API_KEY = os.environ.get("AGENTVERSE_API_KEY", "")
TRUSTED_SENDERS: set[str] = set(
    filter(None, os.environ.get("PYMOL_TRUSTED_SENDERS", "").split(","))
)
RENDER_RATE_LIMIT_SECS = float(os.environ.get("PYMOL_RENDER_RATE_LIMIT", "5.0"))

NGROK_URL = os.environ.get("NGROK_URL", "").rstrip("/")

_endpoints = [f"{NGROK_URL}/submit"] if NGROK_URL else ["http://127.0.0.1:8000/submit"]

agent = Agent(
    name="pymol-bridge",
    seed=SEED,
    port=8000,
    endpoint=_endpoints,
    agentverse="https://agentverse.ai",
    description="PyMOL MCP Bridge — load structures, color, render via natural language",
)

bridge = PyMOLMCPBridge()
_last_render_time: float = 0.0


def _is_trusted(sender: str) -> bool:
    return not TRUSTED_SENDERS or sender in TRUSTED_SENDERS


@agent.on_event("startup")
async def on_startup(ctx: Context):
    await bridge.start()
    ctx.logger.info(f"Agent address: {ctx.agent.address}")
    ctx.logger.info("PyMOL uAgent ready")


@agent.on_event("shutdown")
async def on_shutdown(ctx: Context):
    await bridge.stop()


@agent.on_message(model=PingRequest, replies={PingResponse})
async def handle_ping(ctx: Context, sender: str, msg: PingRequest):
    if not _is_trusted(sender):
        ctx.logger.warning(f"Rejected untrusted sender: {sender}")
        return
    result = await bridge.call_tool("ping_pymol", {})
    await ctx.send(sender, PingResponse(
        success=result["success"],
        version=result["text"],
        message=result["text"],
    ))


@agent.on_message(model=LoadStructureRequest, replies={LoadStructureResponse})
async def handle_load(ctx: Context, sender: str, msg: LoadStructureRequest):
    if not _is_trusted(sender):
        return
    try:
        source = validate_source(msg.source)
    except ValueError as e:
        await ctx.send(sender, LoadStructureResponse(success=False, message=str(e)))
        return
    result = await bridge.call_tool("load_structure", {
        "source": source,
        "object_name": msg.object_name or "",
    })
    await ctx.send(sender, LoadStructureResponse(
        success=result["success"],
        message=result["text"],
    ))


@agent.on_message(model=ColorSelectionRequest, replies={ColorSelectionResponse})
async def handle_color(ctx: Context, sender: str, msg: ColorSelectionRequest):
    if not _is_trusted(sender):
        return
    try:
        color = validate_color(msg.color)
    except ValueError as e:
        await ctx.send(sender, ColorSelectionResponse(success=False, message=str(e)))
        return
    result = await bridge.call_tool("color_selection", {
        "color": color,
        "selection": msg.selection,
    })
    await ctx.send(sender, ColorSelectionResponse(
        success=result["success"],
        message=result["text"],
    ))


@agent.on_message(model=RenderImageRequest, replies={RenderImageResponse})
async def handle_render(ctx: Context, sender: str, msg: RenderImageRequest):
    global _last_render_time
    if not _is_trusted(sender):
        return
    now = asyncio.get_event_loop().time()
    if now - _last_render_time < RENDER_RATE_LIMIT_SECS:
        wait = round(RENDER_RATE_LIMIT_SECS - (now - _last_render_time), 1)
        await ctx.send(sender, RenderImageResponse(
            success=False,
            message=f"Rate limited. Wait {wait}s before next render.",
        ))
        return
    try:
        safe_path = validate_output_path(msg.output_path)
        width, height = validate_dimensions(msg.width, msg.height)
    except ValueError as e:
        await ctx.send(sender, RenderImageResponse(success=False, message=str(e)))
        return
    _last_render_time = now
    result = await bridge.call_tool("render_image", {
        "output_path": safe_path,
        "width": width,
        "height": height,
        "ray_trace": msg.ray_trace,
    })
    await ctx.send(sender, RenderImageResponse(
        success=result["success"],
        message=result["text"],
        image_path=safe_path if result["success"] else "",
    ))


def _parse_chat_command(text: str) -> tuple[str, dict]:
    """Parse natural language into (tool_name, params)."""
    text = text.strip().lower()

    # load <PDB>
    m = re.search(r'\bload\b.*?([a-z0-9]{4})\b', text)
    if m:
        return "load_structure", {"source": m.group(1).upper(), "object_name": ""}

    # color <color> [chain X]
    m = re.search(r'\bcolor\b\s+(\w+)', text)
    if m:
        sel = "all"
        cm = re.search(r'\bchain\s+(\w+)', text)
        if cm:
            sel = f"chain {cm.group(1).upper()}"
        return "color_selection", {"color": m.group(1), "selection": sel}

    # render / screenshot
    if re.search(r'\brender\b|\bscreenshot\b|\bimage\b', text):
        import os, time
        path = os.path.expanduser(f"~/NovoProteinAI/renders/render_{int(time.time())}.png")
        return "render_image", {"output_path": path, "width": 800, "height": 600, "ray_trace": False}

    # ping
    if re.search(r'\bping\b|\bstatus\b|\bconnect', text):
        return "ping_pymol", {}

    return "", {}


chat_proto = Protocol(spec=chat_protocol_spec)


@chat_proto.on_message(model=ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass  # acknowledgements from other agents — no action needed


@chat_proto.on_message(model=ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    # acknowledge receipt
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=msg.timestamp,
        acknowledged_msg_id=msg.msg_id,
    ))

    # extract text
    text = ""
    for item in msg.content:
        if hasattr(item, "text"):
            text += item.text + " "
    text = text.strip()

    if not text:
        reply = "Send me a command like: load 1ABC, color red chain A, render, ping"
    else:
        tool, params = _parse_chat_command(text)
        if not tool:
            reply = f"Unknown command: '{text}'. Try: load <PDB ID>, color <color> [chain X], render, ping"
        else:
            try:
                if tool == "load_structure":
                    params["source"] = validate_source(params["source"])
                elif tool == "color_selection":
                    params["color"] = validate_color(params["color"])
                elif tool == "render_image":
                    params["output_path"] = validate_output_path(params["output_path"])
            except ValueError as e:
                reply = f"Error: {e}"
                tool = ""

            if tool:
                result = await bridge.call_tool(tool, params)
                reply = result["text"] if result["success"] else f"Error: {result['text']}"

    await ctx.send(sender, ChatMessage(
        msg_id=uuid.uuid4(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        content=[TextContent(type="text", text=reply)],
    ))


agent.include(chat_proto, publish_manifest=True)



if __name__ == "__main__":
    agent.run()
