"""
NovoProteinAI — Fetch.ai research agent (the "research layer").

Takes a plain-English vaccine / therapeutic goal (e.g. "build a vaccine for
COVID") and returns a structured target + epitope + known-binder result sourced
from public biology databases. The output is shaped to feed directly into
`render_image(pdb_id, epitope_residues, chain, binder_pdb_id)` in `visualize.py`.

Two ways to use it:
  - As a library / CLI:  `python research_agent.py --goal "build a vaccine for COVID"`
    Runs the research pipeline and prints the JSON contract. Add `--render` to
    also produce a PNG via visualize.render_image().
  - As a Fetch.ai uAgent: `python research_agent.py`  (no flags)
    Starts the ASI:One-compatible chat agent and registers it on Agentverse via
    mailbox so it's discoverable.

Data sources (all real APIs, nothing about the *answer* is hardcoded):
  - PubMed E-utilities  -> citations for the goal
  - RCSB PDB search + data API -> resolve target to a real PDB id + chain,
    and find known antibody / binder complexes
  - IEDB -> epitope residues for the target where available
  - ASI:One (Fetch.ai LLM) -> turn the messy goal into good search terms and
    draft the plain-English explanation

Environment variables:
  ASI_ONE_API_KEY    ASI:One API key (LLM). Optional; the pipeline degrades to a
                     keyword heuristic if missing so it still runs.
  AGENT_SEED         Fixed seed for a stable agent identity/address.
  AGENTVERSE_API_KEY Agentverse API key used for mailbox registration (optional).
  ASI_ONE_BASE_URL   Override ASI:One base url (default https://api.asi1.ai/v1).
  ASI_ONE_MODEL      ASI:One model (default asi1-mini).
"""

import json
import os
import re

import requests

# --- config ---------------------------------------------------------------

ASI_ONE_API_KEY = os.environ.get("ASI_ONE_API_KEY")
ASI_ONE_BASE_URL = os.environ.get("ASI_ONE_BASE_URL", "https://api.asi1.ai/v1")
ASI_ONE_MODEL = os.environ.get("ASI_ONE_MODEL", "asi1-mini")
AGENT_SEED = os.environ.get("AGENT_SEED", "novoprotein-research-seed")
AGENTVERSE_API_KEY = os.environ.get("AGENTVERSE_API_KEY")

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RCSB_SEARCH = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA = "https://data.rcsb.org/rest/v1/core"

HTTP_TIMEOUT = 30

# Last-resort epitope hints, used ONLY when both ASI:One and IEDB are
# unavailable, so the pipeline still returns residues that render. These are
# well-known, publicly documented positions, not a substitute for the live
# lookups above.
_FALLBACK_EPITOPES = {
    "spike": [417, 484, 501],
    "rbd": [417, 484, 501],
    "hemagglutinin": [145, 155, 189],
}


class ResearchError(RuntimeError):
    """Raised for unrecoverable problems while researching a goal."""


# --- ASI:One (Fetch.ai LLM) ----------------------------------------------


def asi_one_chat(prompt, system=None, json_mode=False):
    """
    Call ASI:One (OpenAI-compatible chat completions). Returns the assistant
    text, or None if no key is set or the call fails (callers must fall back).
    """
    if not ASI_ONE_API_KEY:
        return None
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": ASI_ONE_MODEL, "messages": messages, "temperature": 0.2}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        resp = requests.post(
            f"{ASI_ONE_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {ASI_ONE_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


def _asi_one_json(prompt, system=None):
    """ASI:One call that should return a JSON object; parses it or returns None."""
    raw = asi_one_chat(prompt, system=system, json_mode=True)
    if not raw:
        return None
    # Models sometimes wrap JSON in prose / fences; pull out the first object.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


# --- goal -> search terms -------------------------------------------------


def extract_search_terms(goal):
    """
    Turn a messy goal string into structured search terms.

    Returns dict: {target_name, structure_query, pubmed_query}. Uses ASI:One
    when available, otherwise a keyword heuristic so the pipeline still runs.
    """
    data = _asi_one_json(
        "A user wants to design a vaccine or therapeutic. From their goal, "
        "identify the most likely protein TARGET and produce database search "
        "terms. Respond as JSON with keys: target_name (specific protein/domain "
        "name), structure_query (terms to find the antigen structure in the "
        "RCSB PDB), pubmed_query (terms to find relevant papers in PubMed), "
        "organism (NCBI scientific name of the source organism, or null if "
        "unclear).\n\n"
        f"Goal: {goal!r}",
        system="You are a structural biology research assistant. Be precise and concise.",
    )
    if data and data.get("target_name") and data.get("structure_query"):
        organism = data.get("organism")
        return {
            "target_name": str(data["target_name"]),
            "structure_query": str(data["structure_query"]),
            "pubmed_query": str(data.get("pubmed_query") or data["structure_query"]),
            "organism": str(organism) if organism else None,
        }

    # Heuristic fallback: strip filler words, keep the meaningful terms.
    cleaned = re.sub(
        r"\b(build|make|create|design|a|an|the|for|to|of|vaccine|therapeutic|"
        r"treatment|cure|against|protein|please)\b",
        " ",
        goal,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip() or goal.strip()
    target = cleaned
    organism = None
    structure_query = cleaned
    # Light disease -> antigen mapping for the most common asks.
    low = goal.lower()
    if "covid" in low or "sars-cov-2" in low or "coronavirus" in low:
        target = "SARS-CoV-2 spike receptor-binding domain"
        structure_query = "spike receptor-binding domain"
        organism = "Severe acute respiratory syndrome coronavirus 2"
    elif "flu" in low or "influenza" in low:
        target = "Influenza hemagglutinin"
        structure_query = "hemagglutinin"
    return {
        "target_name": target,
        "structure_query": structure_query,
        "pubmed_query": f"{target} vaccine epitope",
        "organism": organism,
    }


# --- PubMed ---------------------------------------------------------------


def search_pubmed(query, retmax=3):
    """Return a list of {title, pmid, url} citations for the query."""
    try:
        ids = (
            requests.get(
                f"{PUBMED_BASE}/esearch.fcgi",
                params={"db": "pubmed", "term": query, "retmode": "json", "retmax": retmax},
                timeout=HTTP_TIMEOUT,
            )
            .json()["esearchresult"]["idlist"]
        )
        if not ids:
            return []
        summary = requests.get(
            f"{PUBMED_BASE}/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            timeout=HTTP_TIMEOUT,
        ).json()["result"]
        citations = []
        for pmid in ids:
            entry = summary.get(pmid, {})
            citations.append(
                {
                    "title": entry.get("title", "").rstrip("."),
                    "pmid": pmid,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                }
            )
        return citations
    except (requests.RequestException, KeyError, ValueError):
        return []


# --- RCSB PDB -------------------------------------------------------------


def _rcsb_search(value, return_type, rows=10, organism=None):
    """
    Run a full-text RCSB search; returns the list of identifier strings.

    When `organism` (an NCBI scientific name) is given, the full-text query is
    AND-ed with a source-organism filter so we don't drift to the wrong species
    (e.g. SARS-CoV vs SARS-CoV-2).
    """
    full_text = {
        "type": "terminal",
        "service": "full_text",
        "parameters": {"value": value},
    }
    if organism:
        node = {
            "type": "group",
            "logical_operator": "and",
            "nodes": [
                full_text,
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entity_source_organism.scientific_name",
                        "operator": "exact_match",
                        "value": organism,
                    },
                },
            ],
        }
    else:
        node = full_text
    query = {
        "query": node,
        "return_type": return_type,
        "request_options": {"paginate": {"start": 0, "rows": rows}},
    }
    try:
        resp = requests.post(RCSB_SEARCH, json=query, timeout=HTTP_TIMEOUT)
        if resp.status_code == 204:  # no hits
            return []
        resp.raise_for_status()
        return [hit["identifier"] for hit in resp.json().get("result_set", [])]
    except (requests.RequestException, KeyError, ValueError):
        return []


def _polymer_entity(entry_id, entity_id):
    """Fetch a polymer entity record, or None."""
    try:
        resp = requests.get(
            f"{RCSB_DATA}/polymer_entity/{entry_id}/{entity_id}", timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


_ANTIBODY_WORDS = ("antibody", "fab", "immunoglobulin", "heavy chain", "light chain", "nanobody", "vhh", "scfv")


def resolve_target_structure(structure_query, target_name, organism=None):
    """
    Resolve the target to a real (pdb_id, chain) pair.

    Searches RCSB at the polymer-entity level so we can pick the chain that is
    the ANTIGEN (matching the target) rather than a bound antibody. Returns
    (pdb_id, chain, description) or (None, None, None) if nothing suitable.
    """
    target_words = [w for w in re.findall(r"[a-z0-9]+", target_name.lower()) if len(w) > 2]
    identifiers = _rcsb_search(structure_query, "polymer_entity", rows=25, organism=organism)
    if not identifiers and organism:
        # Organism filter too strict / name mismatch: retry without it.
        identifiers = _rcsb_search(structure_query, "polymer_entity", rows=25)

    fallback = None  # first valid (pdb, chain) even if description doesn't match
    for ident in identifiers:
        entry_id, _, entity_id = ident.partition("_")
        entity = _polymer_entity(entry_id, entity_id)
        if not entity:
            continue
        desc = (entity.get("rcsb_polymer_entity", {}).get("pdbx_description") or "").lower()
        chains = entity.get("rcsb_polymer_entity_container_identifiers", {}).get("auth_asym_ids") or []
        if not chains:
            continue
        chain = chains[0]
        # Skip antibody chains as the *target*; they're binders, not antigen.
        if any(w in desc for w in _ANTIBODY_WORDS):
            continue
        if fallback is None:
            fallback = (entry_id, chain, desc)
        # Prefer an entity whose description overlaps the target name.
        if any(w in desc for w in target_words):
            return entry_id, chain, desc
    if fallback:
        return fallback
    return None, None, None


def find_binders(structure_query, exclude_pdb, limit=3):
    """Find PDB ids of known antibody / binder complexes for the target."""
    ids = _rcsb_search(f"{structure_query} antibody complex", "entry", rows=15)
    binders = []
    for entry_id in ids:
        pid = entry_id.upper()
        if pid == (exclude_pdb or "").upper():
            continue
        binders.append(pid)
        if len(binders) >= limit:
            break
    return binders


def pdb_exists(pdb_id):
    """Validate that a PDB id actually exists via the RCSB data API."""
    if not pdb_id:
        return False
    try:
        resp = requests.get(f"{RCSB_DATA}/entry/{pdb_id}", timeout=HTTP_TIMEOUT)
        return resp.status_code == 200
    except requests.RequestException:
        return False


# --- epitope residues -----------------------------------------------------


def iedb_epitopes(target_name, limit=8):
    """
    Best-effort epitope residue lookup from IEDB's query API. Returns a list of
    ints (1-based residue positions) or [] if nothing usable comes back.
    """
    try:
        resp = requests.get(
            "https://query-api.iedb.org/epitope_search",
            params={
                "order": "structure_iri",
                "linear_sequence": "neq.null",
                "source_antigen_names": f"cs.{{{target_name}}}",
                "limit": 25,
            },
            timeout=HTTP_TIMEOUT,
        )
        if not resp.ok:
            return []
        residues = set()
        for rec in resp.json():
            start = rec.get("starting_position")
            end = rec.get("ending_position")
            if isinstance(start, int) and isinstance(end, int) and 0 < start <= end:
                residues.update(range(start, end + 1))
        return sorted(residues)[:limit]
    except (requests.RequestException, ValueError):
        return []


def propose_epitope_residues(target_name, pdb_id, chain):
    """
    Determine epitope residues for the target chain.

    Order of preference: ASI:One (knows well-characterized epitopes) -> IEDB ->
    a small documented fallback so rendering still works.
    """
    data = _asi_one_json(
        "Give the author (PDB-numbered) residue positions of the best-known "
        f"neutralizing/antigenic epitope on chain {chain} of PDB {pdb_id} "
        f"(the {target_name}). Respond as JSON: {{\"residues\": [int, ...]}} "
        "with 3-10 positions. Use positions that exist in that chain.",
        system="You are a structural immunology expert. Only return real residue numbers.",
    )
    if data:
        residues = data.get("residues") or data.get("epitope_residues")
        cleaned = [int(r) for r in residues or [] if isinstance(r, (int, float)) and r > 0]
        if cleaned:
            return cleaned

    iedb = iedb_epitopes(target_name)
    if iedb:
        return iedb

    low = target_name.lower()
    for key, residues in _FALLBACK_EPITOPES.items():
        if key in low:
            return list(residues)
    return []


# --- explanation ----------------------------------------------------------


def draft_explanation(goal, target_name, pdb_id, chain, epitope_residues, binders):
    """Write a plain-English summary; ASI:One when available, else a template."""
    facts = (
        f"Goal: {goal}\nTarget: {target_name}\nPDB: {pdb_id} (chain {chain})\n"
        f"Epitope residues: {epitope_residues}\nKnown binders: {binders}"
    )
    text = asi_one_chat(
        "Explain the following protein-design research result in 2-4 sentences "
        "a non-biologist can follow. Do not invent facts beyond what is given.\n\n"
        + facts,
        system="You explain structural biology simply and accurately.",
    )
    if text:
        return text
    binder_note = (
        f" Known binder structures: {', '.join(binders)}." if binders else ""
    )
    return (
        f"For the goal '{goal}', the most relevant target is the {target_name}. "
        f"A real structure is available as PDB {pdb_id} (chain {chain}), and the "
        f"key epitope (the part an immune response or drug would target) is around "
        f"residues {epitope_residues}.{binder_note}"
    )


# --- top-level pipeline ---------------------------------------------------


def research(goal):
    """
    Run the full research pipeline for a goal and return the output contract.

    Always returns a dict matching the documented shape. On no-match it returns
    empty structural fields and an error message in `explanation` (never raises
    for an ordinary "no good target found").
    """
    goal = (goal or "").strip()
    terms = extract_search_terms(goal)
    target_name = terms["target_name"]

    citations = search_pubmed(terms["pubmed_query"])
    pdb_id, chain, _desc = resolve_target_structure(
        terms["structure_query"], target_name, organism=terms.get("organism")
    )

    if not pdb_id or not pdb_exists(pdb_id):
        return {
            "target_name": target_name,
            "pdb_id": "",
            "chain": "",
            "epitope_residues": [],
            "binder_pdb_ids": [],
            "explanation": (
                f"Could not find a reliable experimental structure in the PDB for "
                f"'{goal}' (resolved target: {target_name}). Try a more specific "
                f"target name or pathogen."
            ),
            "citations": citations,
        }

    epitope_residues = propose_epitope_residues(target_name, pdb_id, chain)
    binders = find_binders(terms["structure_query"], exclude_pdb=pdb_id)
    explanation = draft_explanation(goal, target_name, pdb_id, chain, epitope_residues, binders)

    return {
        "target_name": target_name,
        "pdb_id": pdb_id,
        "chain": chain,
        "epitope_residues": epitope_residues,
        "binder_pdb_ids": binders,
        "explanation": explanation,
        "citations": citations,
    }


# --- Fetch.ai uAgent (chat protocol + Agentverse mailbox) -----------------


def build_agent():
    """
    Construct the uAgent with the ASI:One chat protocol and a mailbox so it's
    discoverable on Agentverse. Imported lazily so the research pipeline / CLI
    works even without the uagents stack installed.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from uagents import Agent, Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement,
        ChatMessage,
        EndSessionContent,
        TextContent,
        chat_protocol_spec,
    )

    agent = Agent(name="novoprotein-research", seed=AGENT_SEED, mailbox=True)
    chat_proto = Protocol(spec=chat_protocol_spec)

    def _reply(text):
        return ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[TextContent(type="text", text=text), EndSessionContent(type="end-session")],
        )

    @chat_proto.on_message(ChatMessage)
    async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
        # Acknowledge first so ASI:One / clients know we received the message.
        await ctx.send(
            sender,
            ChatAcknowledgement(
                timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id
            ),
        )
        goal = msg.text()
        ctx.logger.info(f"Research request: {goal!r}")
        try:
            result = research(goal)
        except Exception as exc:  # never let a bad request kill the agent
            ctx.logger.exception("research failed")
            result = {
                "target_name": "",
                "pdb_id": "",
                "chain": "",
                "epitope_residues": [],
                "binder_pdb_ids": [],
                "explanation": f"Internal error while researching the goal: {exc}",
                "citations": [],
            }
        await ctx.send(sender, _reply(json.dumps(result)))

    @chat_proto.on_message(ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"Ack from {sender} for {msg.acknowledged_msg_id}")

    agent.include(chat_proto, publish_manifest=True)
    return agent


# --- CLI ------------------------------------------------------------------


def _main():
    import argparse

    parser = argparse.ArgumentParser(description="NovoProteinAI research agent")
    parser.add_argument("--goal", help="Run the research pipeline for this goal and print JSON.")
    parser.add_argument(
        "--render", action="store_true", help="Also render a PNG via visualize.render_image()."
    )
    parser.add_argument("--out", default="target.png", help="PNG output path for --render.")
    args = parser.parse_args()

    if args.goal:
        result = research(args.goal)
        print(json.dumps(result, indent=2))
        if args.render:
            if not result["pdb_id"]:
                print("\nNo PDB resolved; nothing to render.")
                return
            from visualize import render_image

            binder = result["binder_pdb_ids"][0] if result["binder_pdb_ids"] else None
            path = render_image(
                pdb_id=result["pdb_id"],
                epitope_residues=result["epitope_residues"],
                chain=result["chain"],
                binder_pdb_id=binder,
                out_path=args.out,
            )
            print(f"\nWrote {path}")
        return

    # No goal -> run as the Fetch.ai agent.
    agent = build_agent()
    print(f"Starting agent 'novoprotein-research' at {agent.address}")
    agent.run()


if __name__ == "__main__":
    _main()
