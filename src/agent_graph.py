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

import os
import sys

from langchain_core.tools import tool

try:  # works when imported as part of the `src` package (e.g. tests)
    from . import research_agent as ra
except ImportError:  # works when research_agent is run as a script (src on path)
    import research_agent as ra

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DEFAULT_MODEL = "claude-3-5-sonnet-latest"

SYSTEM_PROMPT = (
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
    """Prefer true MCP adapters; fall back to direct wrappers on any failure."""
    try:
        tools = await _mcp_pymol_tools()
        if tools:
            return tools, "mcp"
    except Exception as exc:  # noqa: BLE001 - we want a robust fallback
        print(f"[agent_graph] MCP tool loading failed ({exc}); using direct wrappers.")
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

    pymol_tools, source = await _load_pymol_tools()
    _tool_source = source
    tools = RESEARCH_TOOLS + pymol_tools

    model = ChatAnthropic(
        model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        temperature=0,
    )
    _graph = create_react_agent(model, tools, prompt=SYSTEM_PROMPT)
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


async def run_agent(message: str) -> str:
    """Run the agentic loop on a user message and return Claude's final reply."""
    graph = await get_graph()
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": message}]}
    )
    return _extract_text(result["messages"][-1])
