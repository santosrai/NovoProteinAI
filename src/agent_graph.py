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
import re
import sys

from langchain_core.tools import tool

try:  # works when imported as part of the `src` package (e.g. tests)
    from . import research_agent as ra
except ImportError:  # works when research_agent is run as a script (src on path)
    import research_agent as ra

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

# The redis_interactions package uses bare imports (e.g. `from schema import ...`),
# so its own directory must be importable for `search_papers` to work.
REDIS_DIR = os.path.join(REPO_ROOT, "redis_interactions")
if os.path.isdir(REDIS_DIR) and REDIS_DIR not in sys.path:
    sys.path.insert(0, REDIS_DIR)

DEFAULT_MODEL = "claude-sonnet-4-6"

BINDER_COMPARISON_WORKFLOW = (
    "When the user has MULTIPLE binder designs (e.g. several loaded complexes "
    "or a folder of design outputs) and wants to compare, rank, or evaluate "
    "them, run the Binder Interface Comparison workflow: "
    "(1) Identify chains in each complex: the TARGET (antigen) chain and the "
    "BINDER (designed nanobody/protein) chain. For these design outputs the "
    "convention is chain A = target, chain B = binder; confirm from "
    "sequence/context or ask the user if ambiguous. "
    "(2) Before computing, verify every object is actually loaded (the PyMOL "
    "session can silently drop objects); if a needed object is missing, reload "
    "it first. "
    "(3) For EACH design, count binder interface residues at ~4 Angstroms with "
    "pymol_select_atoms using a per-object selection so contacts never cross "
    "between objects: byres (OBJ and chain B within 4 of (OBJ and chain A)) and "
    "name CA. The returned atom count equals the residue count (one CA per "
    "residue). Always scope 'within' inside a single object; never run it "
    "across all loaded structures at once. "
    "(4) Highlight in PyMOL: first gray out the whole complex (color gray80 on "
    "all designs), then color the interface residues a distinct color (use "
    "byres WITHOUT 'and name CA' so full residues are colored); you may use "
    "different colors per design or per chain. Then render an image with "
    "pymol_render_image. If many designs are overlaid and the view is crowded, "
    "isolate the top design(s) and re-render for clarity. "
    "(5) Rank the designs by binder interface residue count (highest = most "
    "buried paratope) and present a concise table. Optionally also compute the "
    "reciprocal (target residues near the binder) and flag large asymmetries "
    "between the two counts, since they often indicate glancing contacts or "
    "clashes rather than a real interface. "
    "(6) State clearly that residue-contact count is a proxy for interface "
    "size, not binding affinity. "
    "Robustness: PyMOL MCP calls occasionally fail on the first attempt after "
    "an idle period with a broken-pipe or no-response error; retry once before "
    "reporting a failure."
)

MEMORY_GUIDANCE = (
    "You retain the full conversation. If the user refers to 'it', 'that "
    "structure', or a previous result without naming it, resolve the reference "
    "from earlier turns instead of asking again. Only ask for clarification if "
    "it is genuinely ambiguous."
)

SYSTEM_PROMPT = (
    "You are NovoProteinAI, an agentic research assistant for vaccine and "
    "therapeutic design. Given a plain-English goal you decide which tools to "
    "call: use the research tools to find and validate a protein target (PDB "
    "id, chain) and supporting citations, then use the PyMOL tools to load the "
    "structure, color it, highlight epitope residues, and render an image. "
    "Prefer search_pdb + pdb_exists to find a real, validated structure; you "
    "may call run_research for a one-shot structured summary. "
    "When a question is about a specific paper or protein the project has "
    "ingested, call search_papers to retrieve the relevant chunks: each result "
    "includes the chunk text and any pdb_candidates found in that same chunk. "
    "Choose the PDB id whose surrounding context matches the protein in the "
    "prompt, then ALWAYS confirm it with pdb_exists before loading it (the "
    "candidates are extracted from the paper's wording and may be wrong). If no "
    "candidate validates, fall back to search_pdb. "
    "Always confirm a "
    "PDB id exists before loading it in PyMOL. Be concise in your final answer "
    "and report the target, why it was chosen, and any image you rendered. "
    + BINDER_COMPARISON_WORKFLOW
    + " "
    + MEMORY_GUIDANCE
)


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


# --- paper RAG tool (Redis vector search) -----------------------------------
# A PDB id is a digit (1-9) followed by three alphanumerics, e.g. "6VXX".
_PDB_CODE = r"[1-9][A-Za-z0-9]{3}"
# High-confidence: an id introduced by a cue word ("PDB 6VXX", "RCSB: 6vxx",
# "Protein Data Bank entry 6VXX"). Anchoring to a cue avoids the flood of false
# positives a bare 4-char regex would produce on ordinary tokens.
_PDB_CUE_RE = re.compile(
    r"(?:PDB(?:\s*(?:ID|code|codes|entry|entries|accession))?|RCSB|"
    r"Protein\s+Data\s+Bank)\b[^A-Za-z0-9]{0,15}(" + _PDB_CODE + r")\b",
    re.IGNORECASE,
)


def _extract_pdb_candidates(text: str) -> list:
    """Return PDB ids that appear next to a PDB/RCSB cue word in `text`.

    These are *candidates* from the paper's own wording, not verified ids; the
    agent should confirm each with `pdb_exists` before loading it in PyMOL.
    """
    seen: list[str] = []
    for match in _PDB_CUE_RE.finditer(text or ""):
        code = match.group(1).upper()
        if code not in seen:
            seen.append(code)
    return seen


@tool
def search_papers(
    query: str,
    k: int = 5,
    paper_id: str = "",
    year_min: int = 0,
) -> list:
    """Semantic search over ingested research papers (Redis vector index).

    Use this to ground answers in the project's own papers and to find the PDB
    structure a paper refers to. Returns up to `k` matching chunks; each result
    is a dict with: title, paper_id, section, year, source, content (the chunk
    text), and pdb_candidates (PDB ids detected in that same chunk's text).

    The pdb_candidates come from the paper's wording and are NOT verified —
    pick the one that fits the protein/context and confirm it with pdb_exists
    before loading it in PyMOL. Optionally filter by paper_id or year_min.
    """
    from search import search as _search  # lazy: avoids hard dep at import time

    filters = {}
    if paper_id:
        filters["paper_id"] = paper_id
    if year_min:
        filters["year_min"] = year_min

    rows = _search(query, k=k, **filters)
    results = []
    for r in rows:
        content = r.get("content", "")
        results.append(
            {
                "title": r.get("title", ""),
                "paper_id": r.get("paper_id", ""),
                "section": r.get("section", ""),
                "year": r.get("year", ""),
                "source": r.get("source", ""),
                "content": content[:1200],
                "pdb_candidates": _extract_pdb_candidates(content),
            }
        )
    return results


RESEARCH_TOOLS = [search_pdb, pdb_exists, search_pubmed, run_research, search_papers]


# --- PyMOL tools: relay transport (deployed / public) -----------------------
# The chat handler sets this per request so tool calls route to the right
# user's PyMOL (the one paired to this chat session's token).
current_token: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "current_token", default=None
)


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
        """Render the current PyMOL view to a PNG (saved on the user's machine)."""
        resp = _run_plugin(
            "render_image",
            {
                "output_path": output_path,
                "width": width,
                "height": height,
                "ray_trace": ray_trace,
            },
        )
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
        output_path: str, width: int = 1200, height: int = 900, ray_trace: bool = False
    ) -> str:
        """Render the current PyMOL view to a PNG at output_path."""
        return pt.render_image(output_path, width, height, ray_trace)

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


# --- graph construction -----------------------------------------------------
_graph = None
_tool_source = None


def is_agentic_enabled() -> bool:
    """True if the agentic brain can run (Anthropic key present)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def get_graph():
    """Build and cache the LangGraph ReAct agent."""
    global _graph, _tool_source
    if _graph is not None:
        return _graph

    from langchain_anthropic import ChatAnthropic
    from langgraph.prebuilt import create_react_agent
    from langgraph.checkpoint.memory import MemorySaver

    pymol_tools, source = await _load_pymol_tools()
    _tool_source = source
    tools = RESEARCH_TOOLS + pymol_tools

    model = ChatAnthropic(
        model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        temperature=0,
    )
    _graph = create_react_agent(
        model, tools, prompt=SYSTEM_PROMPT, checkpointer=MemorySaver()
    )
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


async def run_agent(message: str, thread_id: str = "default") -> str:
    """Run the agentic loop on a user message and return Claude's final reply.

    Conversation history is retained per ``thread_id`` via the graph's
    in-memory checkpointer, so only the new message needs to be passed each
    turn. History is kept in memory only and resets when the process restarts.
    """
    graph = await get_graph()
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return _extract_text(result["messages"][-1])
