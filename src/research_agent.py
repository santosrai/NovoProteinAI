"""
NovoProteinAI research agent — a Fetch.ai uAgent for Agentverse / ASI:One.

Takes a plain-English vaccine/therapeutic goal and returns a structured
target + epitope + known-binder result sourced from public biology databases.
The returned JSON matches the inputs of render_image() in visualize.py exactly:
    render_image(pdb_id, epitope_residues, chain, binder_pdb_id)

Run it:
    export AGENT_SEED="some-fixed-phrase"
    export ASI_ONE_API_KEY="..."         # optional; falls back to keyword parsing
    python src/research_agent.py

On first run it prints an Agentverse Inspector/mailbox link. Connect the mailbox
at https://agentverse.ai to make the agent discoverable from ASI:One.
"""

import json
import os
import re

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()  # load AGENT_SEED / ASI_ONE_API_KEY from a local .env if present
except ImportError:
    pass

# --- external API endpoints -------------------------------------------------
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
RCSB_SEARCH = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_ENTRY = "https://data.rcsb.org/rest/v1/core/entry/{id}"
ASI_ONE_URL = "https://api.asi1.ai/v1/chat/completions"

HTTP_TIMEOUT = 30


# --- ASI:One LLM helper -----------------------------------------------------
def asi_one(prompt: str, system: str = "") -> str:
    """Call ASI:One to turn a messy goal into search terms / draft text.

    Returns an empty string when no API key is set or the call fails, so
    callers can fall back to deterministic, key-free behaviour.
    """
    api_key = os.environ.get("ASI_ONE_API_KEY", "")
    if not api_key:
        return ""
    try:
        resp = requests.post(
            ASI_ONE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "asi1-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": system or "You are a biology research assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


# --- data-source helpers ----------------------------------------------------
def search_pdb(query: str) -> list:
    """Resolve a target description to real PDB IDs via the RCSB search API."""
    body = {
        "query": {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        },
        "return_type": "entry",
        "request_options": {"paginate": {"start": 0, "rows": 5}},
    }
    try:
        r = requests.post(RCSB_SEARCH, json=body, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return [hit["identifier"] for hit in r.json().get("result_set", [])]
    except Exception:
        return []


def pdb_exists(pdb_id: str) -> bool:
    """Validate that a PDB ID actually exists before returning it."""
    try:
        r = requests.get(RCSB_ENTRY.format(id=pdb_id), timeout=HTTP_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def search_pubmed(term: str, retmax: int = 3) -> list:
    """Find relevant papers for the goal and return citation dicts."""
    try:
        r = requests.get(
            PUBMED_ESEARCH,
            params={
                "db": "pubmed",
                "term": term,
                "retmax": retmax,
                "retmode": "json",
            },
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        return [
            {
                "title": f"PubMed entry {pmid}",
                "pmid": pmid,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            }
            for pmid in ids
        ]
    except Exception:
        return []


def _keyword_target(goal: str) -> str:
    """Key-free fallback: strip filler words to get a rough search term."""
    stop = {
        "build", "a", "an", "the", "for", "to", "make", "create", "design",
        "vaccine", "therapeutic", "treatment", "cure", "against", "of",
    }
    words = [w for w in goal.lower().split() if w not in stop]
    return " ".join(words).strip() or goal.strip()


# --- main research logic ----------------------------------------------------
def run_research(goal: str) -> dict:
    """Return the JSON contract consumed by visualize.render_image().

    Fields: target_name, pdb_id, chain, epitope_residues, binder_pdb_ids,
    explanation, citations. Never raises on bad input / no match.
    """
    goal = (goal or "").strip()

    # 1. Derive a clean target / search term (ASI:One, else keyword fallback).
    target_name = asi_one(
        f"Goal: {goal}\nReturn ONLY the protein target name to search in the PDB.",
        system="You convert vaccine/therapeutic goals into a single PDB search term.",
    ) or _keyword_target(goal)

    # 2. Resolve to a real, validated PDB ID.
    pdb_id = None
    chain = "A"
    for candidate in search_pdb(target_name):
        if pdb_exists(candidate):
            pdb_id = candidate
            break

    if not pdb_id:
        return {
            "target_name": target_name,
            "pdb_id": None,
            "chain": None,
            "epitope_residues": [],
            "binder_pdb_ids": [],
            "explanation": (
                f"No matching PDB structure was found for '{goal}'. "
                "Try a more specific target (e.g. a named protein or pathogen)."
            ),
            "citations": [],
        }

    # 3. Citations + plain-English summary.
    citations = search_pubmed(target_name)
    explanation = asi_one(
        f"In 2-3 plain sentences a non-biologist understands, explain why PDB "
        f"{pdb_id} is a good target for the goal: {goal}",
    ) or f"{pdb_id} is a structurally characterized target relevant to: {goal}."

    return {
        "target_name": target_name,
        "pdb_id": pdb_id,
        "chain": chain,
        "epitope_residues": [],  # TODO: wire in IEDB epitope ranges
        "binder_pdb_ids": [],
        "explanation": explanation,
        "citations": citations,
    }


# --- PyMOL visualization (via the existing MCP tools) -----------------------
def visualize_target(result: dict, out_path: str = "target.png") -> dict:
    """Render the researched target through the PyMOL MCP tools.

    Reuses `pymol_mcp.tools`, which talks to a running PyMOL plugin over TCP
    (localhost:9877). Best-effort: returns a status dict and never raises, so a
    missing/idle PyMOL doesn't break the research flow.

    Returns: {"ok": bool, "image_path": str | None, "message": str}
    """
    if not result.get("pdb_id"):
        return {"ok": False, "image_path": None, "message": "No pdb_id to visualize."}

    # Make the repo root importable so `pymol_mcp` resolves when run as a script.
    import sys

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # Absolute path so the PyMOL plugin (which may have a different working
    # directory) writes the image where we expect it.
    out_path = os.path.abspath(out_path)

    try:
        from pymol_mcp import tools
    except ImportError as exc:
        return {"ok": False, "image_path": None, "message": f"pymol_mcp unavailable: {exc}"}

    pdb_id = result["pdb_id"]
    chain = result.get("chain")
    epitope = result.get("epitope_residues") or []
    binders = result.get("binder_pdb_ids") or []

    try:
        tools.ping_pymol()  # verify the plugin is reachable before doing work
        tools.load_structure(pdb_id, "target")

        target_sel = f"target and chain {chain}" if chain else "target"
        tools.color_selection("cyan", target_sel)

        if epitope:
            resi = "+".join(str(r) for r in epitope)
            sel = f"target and resi {resi}"
            if chain:
                sel += f" and chain {chain}"
            tools.select_atoms("epitope", sel)
            tools.color_selection("red", "epitope")

        for i, binder in enumerate(binders):
            name = f"binder{i}"
            tools.load_structure(binder, name)
            tools.color_selection("yellow", name)

        # ray_trace=False keeps interactive chat responsive (ray tracing a
        # freshly fetched structure can exceed the client read timeout).
        tools.render_image(out_path, width=1200, height=900, ray_trace=False)
        return {"ok": True, "image_path": out_path, "message": f"Rendered {out_path}"}
    except Exception as exc:  # PyMOL not running / plugin error — stay graceful
        return {
            "ok": False,
            "image_path": None,
            "message": f"Visualization skipped (is PyMOL + plugin running?): {exc}",
        }


# --- direct PyMOL command router --------------------------------------------
_MENTION_RE = re.compile(r"@agent1[0-9a-z]+\s*", re.IGNORECASE)

_PYMOL_COMMANDS = {"ping", "load", "color", "select", "render", "rotate"}


def strip_mention(text: str) -> str:
    """Remove a leading @agent1... mention so the actual command/goal remains."""
    return _MENTION_RE.sub("", text or "").strip()


def handle_pymol_command(text: str):
    """Route a direct PyMOL command to the MCP tools.

    Returns a status string if `text` is a recognized command, else None so
    the caller falls back to research. Never raises.
    """
    cleaned = strip_mention(text)
    parts = cleaned.split()
    if not parts or parts[0].lower() not in _PYMOL_COMMANDS:
        return None

    cmd_name = parts[0].lower()
    args = parts[1:]

    # Make repo root importable so `pymol_mcp` resolves when run as a script.
    import sys

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        from pymol_mcp import tools
    except ImportError as exc:
        return f"pymol_mcp unavailable: {exc}"

    try:
        if cmd_name == "ping":
            return tools.ping_pymol()

        if cmd_name == "load":
            if not args:
                return "Usage: load <pdb_id_or_path> [object_name]"
            return tools.load_structure(args[0], args[1] if len(args) > 1 else None)

        if cmd_name == "color":
            if not args:
                return "Usage: color <color> [selection]"
            selection = " ".join(args[1:]) if len(args) > 1 else "all"
            return tools.color_selection(args[0], selection)

        if cmd_name == "select":
            if len(args) < 2:
                return "Usage: select <name> <selection_expression>"
            return tools.select_atoms(args[0], " ".join(args[1:]))

        if cmd_name == "rotate":
            axis = args[0] if args else "y"
            angle = float(args[1]) if len(args) > 1 else 90.0
            selection = " ".join(args[2:]) if len(args) > 2 else ""
            return tools.rotate(axis, angle, selection)

        if cmd_name == "render":
            out_path = os.path.abspath(args[0] if args else "target.png")
            return tools.render_image(out_path, width=1200, height=900, ray_trace=False)
    except Exception as exc:  # connection/plugin errors -> readable reply
        return f"PyMOL command '{cmd_name}' failed (is PyMOL + plugin running?): {exc}"

    return None


# --- agent + chat protocol --------------------------------------------------
def build_agent():
    """Construct the uAgent with the chat protocol attached.

    Imported lazily so that `run_research` can be used/tested without the
    uagents dependency or an AGENT_SEED env var.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from uagents import Agent, Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatMessage,
        ChatAcknowledgement,
        TextContent,
        chat_protocol_spec,
    )

    agent = Agent(
        name="novoprotein-research",
        seed=os.environ["AGENT_SEED"],
        mailbox=True,
    )

    chat_proto = Protocol(spec=chat_protocol_spec)

    @chat_proto.on_message(ChatMessage)
    async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(
            sender,
            ChatAcknowledgement(
                timestamp=datetime.now(timezone.utc),
                acknowledged_msg_id=msg.msg_id,
            ),
        )
        raw = "".join(
            c.text for c in msg.content if isinstance(c, TextContent)
        )
        text = strip_mention(raw)

        reply_text = None

        # 1. Agentic brain (Claude + LangGraph + MCP tools), if enabled.
        try:
            try:
                from . import agent_graph
            except ImportError:
                import agent_graph

            if agent_graph.is_agentic_enabled():
                ctx.logger.info(f"Agentic goal: {text}")
                reply_text = await agent_graph.run_agent(text)
        except Exception as exc:  # fall back to the deterministic path
            ctx.logger.warning(f"Agentic path failed, falling back: {exc}")
            reply_text = None

        # 2. Fallback: direct PyMOL command (ping/load/color/select/render/rotate)?
        if reply_text is None:
            cmd_reply = handle_pymol_command(text)
            if cmd_reply is not None:
                ctx.logger.info(f"PyMOL command: {text} -> {cmd_reply}")
                reply_text = cmd_reply
            else:
                # 3. Fallback: deterministic research + visualization.
                ctx.logger.info(f"Research goal: {text}")
                result = run_research(text)
                viz = visualize_target(result)
                result["visualization"] = viz
                ctx.logger.info(viz["message"])
                reply_text = json.dumps(result, indent=2)

        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[TextContent(type="text", text=reply_text)],
            ),
        )

    @chat_proto.on_message(ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(chat_proto, publish_manifest=True)
    return agent


if __name__ == "__main__":
    build_agent().run()
