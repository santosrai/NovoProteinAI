"""
Agentic brain for NovoProteinAI: Claude (Anthropic) + LangGraph ReAct agent.

Claude reasons in a loop and calls tools:
  - Research tools  : search_pdb, pdb_exists, search_pubmed, run_research
  - PyMOL tools     : loaded from the pymol_mcp MCP server via langchain-mcp-adapters
                      (stdio), with a direct-wrapper fallback if MCP loading fails.

The Fetch.ai uAgent (research_agent.py) calls `run_agent(message)` from its chat
handler. If Anthropic / LangGraph aren't available, the agent falls back to the
deterministic router in research_agent.py.
"""

import asyncio
import contextvars
import os
import sys

from langchain_core.tools import tool

try:  # works when imported as part of the `src` package (e.g. tests)
    from . import research_agent as ra
except ImportError:  # works when research_agent is run as a script (src on path)
    import research_agent as ra

try:  # RunPod interactive cloud GUI (new, opt-in mode)
    from . import runpod_gui
except ImportError:
    try:
        import runpod_gui  # type: ignore
    except ImportError:
        runpod_gui = None  # RunPod client unavailable (e.g. requests missing)

try:  # relay is used when the agent is deployed publicly (Railway)
    from . import relay
except ImportError:
    try:
        import relay  # type: ignore
    except ImportError:
        relay = None  # local-only mode without the relay package

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DEFAULT_MODEL = "claude-3-5-sonnet-latest"

BASE_PROMPT = (
    "You are NovoProteinAI, an agentic research assistant for vaccine and "
    "therapeutic design. Given a plain-English goal you decide which tools to "
    "call: use the research tools to find and validate a protein target (PDB "
    "id, chain) and supporting citations, then use the PyMOL tools to load the "
    "structure, color it, highlight epitope residues, and render an image. "
    "Prefer search_pdb + pdb_exists to find a real, validated structure; you "
    "may call run_research for a one-shot structured summary. Always confirm a "
    "PDB id exists before loading it in PyMOL. Be concise in your final answer "
    "and report the target, why it was chosen, and any image you rendered."
)

# PyMOL guidance appended to BASE_PROMPT depending on the PYMOL_CLOUD toggle.
CLOUD_PYMOL_PROMPT = (
    " PyMOL runs as a live cloud session. When the user wants to see, explore, "
    "rotate, or open a structure, call launch_interactive_gui to start it and "
    "share the returned browser link; you can then load/color/select/render in "
    "that same live session with the pymol_* tools. When the user is done, call "
    "close_interactive_gui to shut it down. If the user wants a screenshot or an "
    "easier way to see the structure, call pymol_render_image: the rendered "
    "image is delivered to them inline in the chat alongside the viewer link."
)
LOCAL_PYMOL_PROMPT = (
    " PyMOL runs locally on the user's machine. Use the pymol_* tools "
    "(pymol_load_structure, pymol_color_selection, pymol_render_image, etc.) to "
    "operate it and render images for the user. When the user asks to see a "
    "structure or a screenshot, call pymol_render_image: the rendered image is "
    "shown to them inline in the chat."
)

# Back-compat alias (older imports referenced SYSTEM_PROMPT).
SYSTEM_PROMPT = BASE_PROMPT


# --- research tools ---------------------------------------------------------
@tool
def search_pdb(query: str) -> list:
    """Search the RCSB PDB for structures matching a free-text query.

    Returns a list of candidate PDB IDs (most relevant first).
    """
    return ra.search_pdb(query)


@tool
def pdb_exists(pdb_id: str) -> bool:
    """Return True if the given PDB ID exists in the RCSB database."""
    return ra.pdb_exists(pdb_id)


@tool
def search_pubmed(term: str) -> list:
    """Search PubMed for a term. Returns citation dicts (title, pmid, url)."""
    return ra.search_pubmed(term)


@tool
def run_research(goal: str) -> dict:
    """One-shot research pipeline: turn a goal into a structured target result.

    Returns target_name, pdb_id, chain, epitope_residues, binder_pdb_ids,
    explanation and citations.
    """
    return ra.run_research(goal)


RESEARCH_TOOLS = [search_pdb, pdb_exists, search_pubmed, run_research]


# --- PyMOL tools: relay transport (deployed / public) -----------------------
# The chat handler sets this per request so tool calls route to the right
# user's PyMOL (the one paired to this chat session's token).
current_token: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "current_token", default=None
)


# --- interactive cloud GUI session tracking ---------------------------------
# Maps a session key (the paired token, or "_local" when unpaired) to the
# RunPod job id of that session's live PyMOL GUI. Tools mutate this so the chat
# handler can close the session on "done"/disconnect (see research_agent.py).
_active_jobs: "dict[str, str]" = {}


def _session_key() -> str:
    """Key for the current chat session (token, or a local sentinel)."""
    return current_token.get() or "_local"


def get_active_job(token: "str | None") -> "str | None":
    """Return the RunPod job id for a session token, if one is live."""
    return _active_jobs.get(token or "_local")


def clear_active_job(token: "str | None") -> None:
    """Forget the tracked job for a session token."""
    _active_jobs.pop(token or "_local", None)


# --- rendered image capture -------------------------------------------------
# Maps a session key to the most recent rendered PNG bytes produced during a
# turn. The chat handler pops this after run_agent() to deliver the screenshot
# inline as a chat image attachment.
_last_images: "dict[str, bytes]" = {}


def _store_last_image(data: "bytes | None") -> None:
    """Record rendered image bytes for the current session (best-effort)."""
    if data:
        _last_images[_session_key()] = data


def pop_last_image(token: "str | None") -> "bytes | None":
    """Return and clear the last rendered image bytes for a session token."""
    return _last_images.pop(token or "_local", None)


# --- conversation memory ----------------------------------------------------
# Per-session chat history so the agent remembers context across turns. To keep
# token usage low we store only the compact user/assistant text (NOT the verbose
# tool-call traces) and keep just the most recent messages (MAX_HISTORY_MESSAGES,
# default 12 = ~6 exchanges). Set MAX_HISTORY_MESSAGES=0 to disable memory.
_MAX_HISTORY_MESSAGES = int(os.environ.get("MAX_HISTORY_MESSAGES", "12"))
_histories: "dict[str, list[dict]]" = {}


def reset_history(session_id: "str | None") -> None:
    """Forget the stored conversation history for a session."""
    _histories.pop(session_id or "_local", None)


def _run_plugin(method: str, params: dict) -> dict:
    """Send a JSON-RPC command to the paired user's PyMOL via the relay.

    Bridges the synchronous LangGraph tool call to the relay's async loop using
    run_coroutine_threadsafe. Returns the plugin's JSON-RPC response dict (or a
    JSON-RPC-style error dict). Never raises.
    """
    if relay is None:
        return {"error": {"code": -32601, "message": "Relay not available in this build."}}

    token = current_token.get()
    if not token:
        return {
            "error": {
                "code": -32300,
                "message": "This chat session is not paired. Send 'pair <token>' first.",
            }
        }

    loop = relay.get_loop()
    if loop is None:
        return {"error": {"code": -32300, "message": "Relay is not running yet."}}

    try:
        fut = asyncio.run_coroutine_threadsafe(
            relay.call_plugin(token, method, params), loop
        )
        return fut.result(timeout=70)
    except Exception as exc:  # noqa: BLE001 - surface as a readable tool result
        return {"error": {"code": -32603, "message": f"Relay call failed: {exc}"}}


def _plugin_result_text(response: dict, ok_default: str = "OK") -> str:
    """Normalize a plugin JSON-RPC response into a readable tool string."""
    if "error" in response:
        err = response["error"]
        raise Exception(f"PyMOL error ({err.get('code')}): {err.get('message')}")
    result = response.get("result", {})
    if isinstance(result, dict):
        return result.get("message") or ok_default
    return str(result)


def _relay_pymol_tools():
    """PyMOL tools that route over the relay to the user's local PyMOL."""

    @tool
    def pymol_ping() -> str:
        """Check the PyMOL connection and return its version."""
        resp = _run_plugin("ping", {})
        if "error" in resp:
            err = resp["error"]
            raise Exception(f"PyMOL error ({err.get('code')}): {err.get('message')}")
        result = resp.get("result", {})
        return f"✓ PyMOL connected (version {result.get('version', 'unknown')})"

    @tool
    def pymol_load_structure(source: str, object_name: str = "") -> str:
        """Load a PDB ID or structure file into PyMOL."""
        resp = _run_plugin(
            "load_structure", {"source": source, "object_name": object_name or ""}
        )
        return f"✓ {_plugin_result_text(resp, 'Structure loaded')}"

    @tool
    def pymol_select_atoms(selection_name: str, selection_expr: str) -> str:
        """Create a named PyMOL selection (e.g. 'chain A and resi 1-10')."""
        resp = _run_plugin(
            "select_atoms",
            {"selection_name": selection_name, "selection_expr": selection_expr},
        )
        return f"✓ {_plugin_result_text(resp, 'Selection created')}"

    @tool
    def pymol_color_selection(color: str, selection: str = "all") -> str:
        """Color a PyMOL selection (e.g. color 'red' on selection 'chain A')."""
        resp = _run_plugin("color_selection", {"color": color, "selection": selection})
        return f"✓ {_plugin_result_text(resp, 'Colored')}"

    @tool
    def pymol_rotate(axis: str = "y", angle: float = 90, selection: str = "") -> str:
        """Rotate the camera or a selection about an axis (x/y/z)."""
        resp = _run_plugin(
            "rotate", {"axis": axis, "angle": angle, "selection": selection}
        )
        return f"✓ {_plugin_result_text(resp, 'Rotated')}"

    @tool
    def pymol_render_image(
        output_path: str = "target.png",
        width: int = 1200,
        height: int = 900,
        ray_trace: bool = False,
    ) -> str:
        """Render the current PyMOL view to a PNG and show it to the user.

        The rendered image is delivered inline as a chat attachment, so the
        user sees the screenshot directly (in addition to it being saved).
        """
        resp = _run_plugin(
            "render_image",
            {
                "output_path": output_path,
                "width": width,
                "height": height,
                "ray_trace": ray_trace,
            },
        )
        if isinstance(resp, dict):
            result = resp.get("result", {})
            b64 = result.get("image_base64") if isinstance(result, dict) else None
            if b64:
                import base64

                try:
                    _store_last_image(base64.b64decode(b64))
                except Exception:  # noqa: BLE001 - never break the tool call
                    pass
        return f"✓ {_plugin_result_text(resp, 'Image rendered')}"

    return [
        pymol_ping,
        pymol_load_structure,
        pymol_select_atoms,
        pymol_color_selection,
        pymol_rotate,
        pymol_render_image,
    ]


# --- PyMOL tools: direct-wrapper fallback -----------------------------------
def _direct_pymol_tools():
    """Wrap pymol_mcp.tools as LangChain tools (used if MCP loading fails)."""
    from pymol_mcp import tools as pt

    @tool
    def pymol_ping() -> str:
        """Check the PyMOL connection and return its version."""
        return pt.ping_pymol()

    @tool
    def pymol_load_structure(source: str, object_name: str = "") -> str:
        """Load a PDB ID or structure file into PyMOL."""
        return pt.load_structure(source, object_name or None)

    @tool
    def pymol_select_atoms(selection_name: str, selection_expr: str) -> str:
        """Create a named PyMOL selection (e.g. 'chain A and resi 1-10')."""
        return pt.select_atoms(selection_name, selection_expr)

    @tool
    def pymol_color_selection(color: str, selection: str = "all") -> str:
        """Color a PyMOL selection (e.g. color 'red' on selection 'chain A')."""
        return pt.color_selection(color, selection)

    @tool
    def pymol_rotate(axis: str = "y", angle: float = 90, selection: str = "") -> str:
        """Rotate the camera or a selection about an axis (x/y/z)."""
        return pt.rotate(axis, angle, selection)

    @tool
    def pymol_render_image(
        output_path: str = "target.png",
        width: int = 1200,
        height: int = 900,
        ray_trace: bool = False,
    ) -> str:
        """Render the current PyMOL view to a PNG and show it to the user.

        The rendered image is delivered inline as a chat attachment.
        """
        msg = pt.render_image(output_path, width, height, ray_trace)
        try:
            import os as _os

            if _os.path.exists(output_path):
                with open(output_path, "rb") as fh:
                    _store_last_image(fh.read())
        except Exception:  # noqa: BLE001 - never break the tool call
            pass
        return msg

    return [
        pymol_ping,
        pymol_load_structure,
        pymol_select_atoms,
        pymol_color_selection,
        pymol_rotate,
        pymol_render_image,
    ]


# --- PyMOL tools: true MCP via adapters -------------------------------------
async def _mcp_pymol_tools():
    """Load PyMOL tools from the pymol_mcp MCP server over stdio."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            "pymol": {
                "command": sys.executable,
                "args": ["-m", "pymol_mcp.server"],
                "transport": "stdio",
                "cwd": REPO_ROOT,
            }
        }
    )
    return await client.get_tools()


async def _load_pymol_tools():
    """Select the PyMOL tool transport.

    Controlled by PYMOL_TRANSPORT:
      - "relay" (default): route over the relay to each user's local PyMOL.
        This is the deployed/public mode (agent on Railway, PyMOL on laptops).
      - "mcp"  : load tools from the local pymol_mcp MCP server (stdio).
      - "local"/"direct": direct wrappers around pymol_mcp.tools (localhost TCP).

    MCP/direct are for single-machine local development only.
    """
    transport = os.environ.get("PYMOL_TRANSPORT", "relay").lower()

    if transport == "relay":
        if relay is None:
            print("[agent_graph] relay unavailable; falling back to direct wrappers.")
            return _direct_pymol_tools(), "direct"
        return _relay_pymol_tools(), "relay"

    if transport == "mcp":
        try:
            tools = await _mcp_pymol_tools()
            if tools:
                return tools, "mcp"
        except Exception as exc:  # noqa: BLE001 - we want a robust fallback
            print(f"[agent_graph] MCP tool loading failed ({exc}); using direct wrappers.")
        return _direct_pymol_tools(), "direct"

    return _direct_pymol_tools(), "direct"


# --- interactive cloud GUI tools (RunPod, opt-in) ---------------------------
def _interactive_gui_tools():
    """Tools that launch/close a live PyMOL GUI on RunPod over noVNC.

    Self-gating: if RunPod isn't configured the tools return a friendly message
    instead of failing, so they can always be registered.
    """

    @tool
    def launch_interactive_gui(pdb_id: str, chain: str = "", epitope: str = "") -> str:
        """Open a live, interactive PyMOL session in the user's browser.

        Boots a cloud PyMOL GUI preloaded with the given PDB id (optionally
        styled by chain and a '+'-joined epitope residue list, e.g. '12+15+19')
        and returns a clickable link. Use this when the user wants to explore,
        rotate, or interact with a structure rather than just see a static image.
        """
        if runpod_gui is None:
            return "Interactive cloud GUI is unavailable in this build."
        token = current_token.get()
        # Reuse an existing session for this chat rather than stacking workers.
        existing = get_active_job(token)
        if existing:
            runpod_gui.close_gui(existing)
            clear_active_job(token)
        # If a public relay URL is configured, the cloud PyMOL dials out to it
        # under this session's token so the agent's relay tools can drive it.
        relay_url = os.environ.get("PUBLIC_RELAY_URL", "")
        res = runpod_gui.launch_gui(
            pdb_id, chain or "", epitope or "",
            relay_url=relay_url if token else "",
            token=token or "",
        )
        if res.get("ok") and res.get("job_id"):
            _active_jobs[_session_key()] = res["job_id"]
            control = (
                " I can also load/color/render in this live session for you."
                if relay_url and token else ""
            )
            return (
                f"Interactive 3D viewer ready: [Open in browser]({res['url']})\n"
                f"Click the link to explore the structure.{control} Tell me when "
                "you're done so I can shut the session down."
            )
        return res.get("message", "Failed to launch the interactive GUI.")

    @tool
    def close_interactive_gui() -> str:
        """Shut down this chat session's live interactive PyMOL GUI (stops billing)."""
        if runpod_gui is None:
            return "Interactive cloud GUI is unavailable in this build."
        token = current_token.get()
        job_id = get_active_job(token)
        if not job_id:
            return "There is no interactive session to close."
        res = runpod_gui.close_gui(job_id)
        clear_active_job(token)
        return res.get("message", "Closed the interactive session.")

    return [launch_interactive_gui, close_interactive_gui]


# --- graph construction -----------------------------------------------------
_graph = None
_tool_source = None


def is_agentic_enabled() -> bool:
    """True if the agentic brain can run (Anthropic key present)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def is_cloud_pymol() -> bool:
    """True if the agent should use the RunPod cloud PyMOL (env PYMOL_CLOUD).

    When enabled, the interactive cloud-GUI tools are offered and the prompt
    steers visualization to a live cloud session. When disabled (default), the
    agent drives the user's local PyMOL instead.
    """
    return os.environ.get("PYMOL_CLOUD", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


async def get_graph():
    """Build and cache the LangGraph ReAct agent."""
    global _graph, _tool_source
    if _graph is not None:
        return _graph

    from langchain_anthropic import ChatAnthropic
    from langgraph.prebuilt import create_react_agent

    pymol_tools, source = await _load_pymol_tools()
    _tool_source = source

    # PYMOL_CLOUD selects the PyMOL backend: cloud (RunPod live GUI) vs local.
    cloud = is_cloud_pymol()
    tools = RESEARCH_TOOLS + pymol_tools
    if cloud:
        tools += _interactive_gui_tools()
    prompt = BASE_PROMPT + (CLOUD_PYMOL_PROMPT if cloud else LOCAL_PYMOL_PROMPT)

    model = ChatAnthropic(
        model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        temperature=0,
    )
    _graph = create_react_agent(model, tools, prompt=prompt)
    return _graph


def _extract_text(message) -> str:
    """Normalize an AIMessage content (str or list of blocks) to plain text."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(content)


async def run_agent(message: str, session_id: "str | None" = None) -> str:
    """Run the agentic loop on a user message and return Claude's final reply.

    Conversation memory: prior turns for `session_id` are prepended so the agent
    has context. Only compact user/assistant text is retained (capped at
    MAX_HISTORY_MESSAGES), keeping token usage low.
    """
    key = session_id or _session_key()
    # Clear any stale screenshot so we only deliver one rendered this turn.
    _last_images.pop(_session_key(), None)
    graph = await get_graph()

    history = _histories.get(key, []) if _MAX_HISTORY_MESSAGES > 0 else []
    messages = history + [{"role": "user", "content": message}]
    result = await graph.ainvoke({"messages": messages})
    reply = _extract_text(result["messages"][-1])

    # Persist a compact transcript (user prompt + final assistant text only) and
    # trim to the most recent messages so history can't grow unbounded.
    if _MAX_HISTORY_MESSAGES > 0:
        updated = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ]
        _histories[key] = updated[-_MAX_HISTORY_MESSAGES:]
    return reply
