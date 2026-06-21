import asyncio
import json
import logging
import os
import re
import time
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


_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_INTENT_SYSTEM = """You control PyMOL molecular visualization software.
Parse the user's message and return ONLY a JSON object (no markdown, no explanation).

Schema:
{"tool": "<tool_name>", "params": {<params>}}

Available tools:
- "load_structure": load a protein. params: {"source": "<4-char PDB ID>", "object_name": ""}
- "color_selection": color atoms. params: {"color": "<color_name>", "selection": "<pymol_selection>"}
  selection examples: "all", "chain A", "chain B", "resn HEM"
  color must be one of: red blue green yellow cyan magenta orange white black gray pink purple salmon slate teal violet wheat
- "render_image": take a screenshot. params: {"output_path": "", "width": 800, "height": 600, "ray_trace": false}
- "ping_pymol": check connection. params: {}
- "unknown": cannot parse. params: {}

Examples:
"color the chain A red" → {"tool":"color_selection","params":{"color":"red","selection":"chain A"}}
"make everything blue" → {"tool":"color_selection","params":{"color":"blue","selection":"all"}}
"fetch 1ABC" → {"tool":"load_structure","params":{"source":"1ABC","object_name":""}}
"take a screenshot" → {"tool":"render_image","params":{"output_path":"","width":800,"height":600,"ray_trace":false}}
"is pymol running?" → {"tool":"ping_pymol","params":{}}"""


async def _parse_with_llm(text: str) -> tuple[str, dict]:
    """Use Claude to parse free-form English into a PyMOL tool call."""
    if not _ANTHROPIC_API_KEY:
        return "", {}
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=_ANTHROPIC_API_KEY)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = msg.content[0].text.strip()
        data = json.loads(raw)
        tool = data.get("tool", "unknown")
        params = data.get("params", {})
        if tool == "unknown":
            return "", {}
        # fill in render path if empty
        if tool == "render_image" and not params.get("output_path"):
            params["output_path"] = os.path.expanduser(
                f"~/NovoProteinAI/renders/render_{int(time.time())}.png"
            )
        return tool, params
    except Exception as e:
        logger.warning(f"LLM parse failed: {e}")
        return "", {}


def _parse_with_regex(text: str) -> tuple[str, dict]:
    """Regex fallback — used when no ANTHROPIC_API_KEY or LLM fails."""
    t = text.strip().lower()

    # load: PDB IDs always start with a digit (e.g. 2HHB, 1ABC)
    m = re.search(r'\b([0-9][a-z0-9]{3})\b', t)
    if m and re.search(r'\b(load|fetch|open|import|get|show)\b', t):
        return "load_structure", {"source": m.group(1).upper(), "object_name": ""}

    # color: extract known color anywhere in sentence, chain anywhere
    from .validators import VALID_COLORS
    found_color = next((c for c in VALID_COLORS if re.search(rf'\b{c}\b', t)), None)
    if found_color and re.search(r'\b(color|colour|paint|highlight|make|set)\b', t):
        sel = "all"
        cm = re.search(r'\bchain\s+(\w+)', t)
        if cm and cm.group(1) not in VALID_COLORS:
            sel = f"chain {cm.group(1).upper()}"
        return "color_selection", {"color": found_color, "selection": sel}

    if re.search(r'\b(render|screenshot|image|picture|photo|save)\b', t):
        return "render_image", {
            "output_path": os.path.expanduser(f"~/NovoProteinAI/renders/render_{int(time.time())}.png"),
            "width": 800, "height": 600, "ray_trace": False,
        }

    if re.search(r'\b(ping|status|connect|running|alive|check)', t):
        return "ping_pymol", {}

    return "", {}


async def _parse_chat_command(text: str) -> tuple[str, dict]:
    if _ANTHROPIC_API_KEY:
        tool, params = await _parse_with_llm(text)
        if tool:
            return tool, params
    return _parse_with_regex(text)


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
        tool, params = await _parse_chat_command(text)
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
