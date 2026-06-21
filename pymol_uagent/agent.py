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

_INTENT_SYSTEM = """You are PyMOLS, a friendly AI assistant that controls PyMOL and loves talking about structural biology.

Return ONLY a JSON object — no markdown, no explanation.

## Single PyMOL action:
{"intent": "pymol_command", "tool": "<tool>", "params": {...}}

## Multiple actions in one message (e.g. "load 2HHB and color it blue"):
{"intent": "pymol_commands", "commands": [{"tool": "<tool>", "params": {...}}, ...]}

Available tools:
- "load_structure": params: {"source": "<4-char PDB ID>", "object_name": ""}
- "color_selection": params: {"color": "<color>", "selection": "<pymol_selection>"}
  valid colors: red blue green yellow cyan magenta orange white black gray pink purple salmon slate teal violet wheat
  selection examples: "all", "chain A", "chain B"
- "render_image": params: {"output_path": "", "width": 800, "height": 600, "ray_trace": false}
- "ping_pymol": params: {}

## Biology/protein/PyMOL question — answer like a knowledgeable friend, short and direct, no bullet lists:
{"intent": "conversation", "reply": "<2-3 friendly sentences>"}

## Unrelated to molecular biology — one brief sentence, friendly nudge back:
{"intent": "out_of_scope", "reply": "<one sentence>"}

Examples:
"load 2HHB and make it blue" → {"intent":"pymol_commands","commands":[{"tool":"load_structure","params":{"source":"2HHB","object_name":""}},{"tool":"color_selection","params":{"color":"blue","selection":"all"}}]}
"color the chain A red" → {"intent":"pymol_command","tool":"color_selection","params":{"color":"red","selection":"chain A"}}
"what is hemoglobin?" → {"intent":"conversation","reply":"Hemoglobin is the oxygen-carrying protein in red blood cells — four chains each hugging a heme group that grabs O2 in the lungs and drops it off in tissues. PDB 2HHB is the classic deoxy form, great for visualizing the T-state conformation."}
"what's the weather?" → {"intent":"out_of_scope","reply":"Ha, weather's outside my expertise — I live in PDB land. Ask me to load a structure or tell you about a protein!"}"""


async def _parse_with_llm(text: str) -> tuple[str, dict]:
    """Classify intent and return (tool, params) or ("__reply__", {"text": ...})."""
    if not _ANTHROPIC_API_KEY:
        return "", {}
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=_ANTHROPIC_API_KEY)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = msg.content[0].text.strip()
        data = json.loads(raw)
        intent = data.get("intent", "out_of_scope")

        if intent == "pymol_commands":
            return "__commands__", {"commands": data.get("commands", [])}

        if intent == "pymol_command":
            tool = data.get("tool", "")
            params = data.get("params", {})
            if not tool:
                return "", {}
            if tool == "render_image" and not params.get("output_path"):
                params["output_path"] = os.path.expanduser(
                    f"~/NovoProteinAI/renders/render_{int(time.time())}.png"
                )
            return tool, params

        reply = data.get("reply", "I can help with PyMOL commands and protein biology questions.")
        return "__reply__", {"text": reply}

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


_ACTION_REPLIES = {
    "load_structure": lambda p, t: f"Got it — {t}",
    "color_selection": lambda p, t: f"Done! {t}",
    "render_image": lambda p, t: f"Rendered! Saved as {p.get('output_path', '').split('/')[-1]}",
    "ping_pymol": lambda p, t: f"PyMOL is alive ✓ ({t})",
}


async def _execute_tool(tool: str, params: dict) -> str:
    try:
        if tool == "load_structure":
            params["source"] = validate_source(params["source"])
        elif tool == "color_selection":
            params["color"] = validate_color(params["color"])
        elif tool == "render_image":
            params["output_path"] = validate_output_path(params["output_path"])
    except ValueError as e:
        return f"Error: {e}"
    result = await bridge.call_tool(tool, params)
    if not result["success"]:
        return f"Hmm, that didn't work: {result['text']}"
    fmt = _ACTION_REPLIES.get(tool)
    return fmt(params, result["text"]) if fmt else result["text"]


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
        reply = "Hi! I'm PyMOLS. Ask me to load a protein, color a chain, render an image, or just ask a biology question!"
    else:
        tool, params = await _parse_chat_command(text)
        if tool == "__reply__":
            reply = params["text"]
        elif tool == "__commands__":
            parts = [await _execute_tool(cmd["tool"], cmd["params"]) for cmd in params["commands"]]
            reply = " → ".join(parts)
        elif tool:
            reply = await _execute_tool(tool, params)
        else:
            reply = "Not sure what you mean — try 'load 2HHB' or ask me a protein biology question."

    await ctx.send(sender, ChatMessage(
        msg_id=uuid.uuid4(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        content=[TextContent(type="text", text=reply)],
    ))


agent.include(chat_proto, publish_manifest=True)



if __name__ == "__main__":
    agent.run()
