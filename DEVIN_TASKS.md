# Devin Task Specs — NovoProteinAI

Paste these one at a time into Devin. Each is scoped to be completable independently.

---

## Task 1 — Fetch.ai research agent (the "research layer")

**Goal:** Build a Fetch.ai uAgent that takes a plain-English vaccine/therapeutic goal
and returns a structured target + epitope + known-binder result, sourced from public
biology databases. It must be ASI:One-discoverable and registered on Agentverse.

**Repo:** `github.com/santosrai/NovoProteinAI`. Add the agent as `research_agent.py`
at the repo root. Do NOT modify `visualize.py` — your output must match its inputs.

### Hard output contract (this is the whole point — match it exactly)
The agent must return a JSON object with these fields:
```json
{
  "target_name": "SARS-CoV-2 spike receptor-binding domain",
  "pdb_id": "6VXX",
  "chain": "A",
  "epitope_residues": [417, 484, 501],
  "binder_pdb_ids": ["7K8M"],
  "explanation": "Plain-English summary a non-biologist can follow.",
  "citations": [
    {"title": "...", "pmid": "...", "url": "https://pubmed.ncbi.nlm.nih.gov/..."}
  ]
}
```
`pdb_id` (str), `chain` (str), and `epitope_residues` (list[int]) are REQUIRED and
feed directly into `render_image(pdb_id, epitope_residues, chain, binder_pdb_id)` in
`visualize.py`. `binder_pdb_ids` may be an empty list. Validate that `pdb_id` actually
exists in the PDB before returning.

### Data sources (use real APIs, no hardcoding)
- **PubMed** (E-utilities): `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`
  and `efetch.fcgi` — find relevant papers for the goal, return citations.
- **RCSB PDB** search + data API: `https://search.rcsb.org/rcsbsearch/v2/query` and
  `https://data.rcsb.org/rest/v1/core/entry/{id}` — resolve target → a real PDB ID,
  identify the relevant chain, and find known antibody/binder complexes.
- **IEDB**: epitope residue ranges for the target where available.

### Fetch.ai requirements (for the sponsor track)
- `pip install uagents` (add to `requirements.txt`).
- Implement with the **chat protocol** so the agent is ASI:One-compatible
  (see https://uagents.fetch.ai/docs/guides/chat_protocol).
- Register on **Agentverse** via mailbox so it's discoverable.
- Use **ASI:One** (Fetch.ai's LLM) to turn the messy goal string into good database
  search terms and to draft the `explanation` field. API key via env var `ASI_ONE_API_KEY`.
- Agent name: `novoprotein-research`. Use a fixed `seed` from env `AGENT_SEED`.

### Acceptance criteria
1. Running the agent and sending it `"build a vaccine for COVID"` returns a valid
   object matching the contract above, with a real `pdb_id`.
2. The returned `pdb_id`/`chain`/`epitope_residues` produce an image when passed to
   `render_image()` (test this end-to-end and include the resulting PNG in the PR).
3. Agent is registered on Agentverse and reachable via the chat protocol.
4. `requirements.txt` updated; a short `README` section documents how to run it and
   which env vars are needed.
5. Graceful handling when a goal has no good PDB match (return a clear error in
   `explanation`, don't crash).

### Out of scope (do not build these here)
- The orchestrator/conversation layer (that's Task 2), the PyMOL renderer
  (already done), any frontend.

---

## Task 2 — Orchestrator agent (Fetch.ai, ASI:One-fronted)

**Goal:** Build a second Fetch.ai uAgent that is the conversational "front door"
of the app. The user talks to **ASI:One**, which discovers and routes to this
orchestrator agent via the chat protocol. The orchestrator coordinates the other
pieces — it does NOT do research or rendering itself, it calls them.

**Depends on Task 1** (the research agent). Reuse the same message models /
output contract so the two agents speak the same language.

**Repo:** `github.com/santosrai/NovoProteinAI`. Add as `orchestrator_agent.py` at
the repo root. Do NOT modify `visualize.py` or `research_agent.py` beyond importing
from them.

### Flow
```
User  ⇄  ASI:One  ⇄  orchestrator_agent  ──▶ research_agent (Task 1)  → {pdb_id, chain, epitope_residues, binder_pdb_ids, citations}
                                          └─▶ visualize.render_image(...) → PNG
```
On receiving a user goal via the chat protocol, the orchestrator must:
1. Use **ASI:One** to interpret the user's intent and explain key terms
   (antibody, epitope, binder, etc.) in beginner-friendly language.
2. Message the **research agent** (`novoprotein-research`) with the goal and
   await its structured result.
3. Call `render_image(pdb_id, epitope_residues, chain, binder_pdb_id)` from
   `visualize.py` to produce the PNG.
4. Reply via the chat protocol with: the plain-English explanation, a target
   summary, the paper citations, and a reference/path to the rendered image.

### Fetch.ai requirements (for the sponsor track)
- Built with `uagents`, uses the **chat protocol**, ASI:One-compatible.
- Registered on **Agentverse** via mailbox (so ASI:One can route to it).
- Agent name: `novoprotein-orchestrator`. Fixed `seed` from env `ORCH_AGENT_SEED`
  (different seed from the research agent).
- Research agent address via env `RESEARCH_AGENT_ADDRESS`; ASI:One key via
  `ASI_ONE_API_KEY`.
- Define shared request/response `Model`s so the two agents communicate cleanly.

### Acceptance criteria
1. Sending "build a vaccine for COVID" through ASI:One (or the chat protocol)
   yields: a plain-English explanation, target info, citations, and a rendered
   image — end to end across both agents.
2. The orchestrator actually messages the research agent and consumes its
   structured response (no duplicated research logic).
3. Both agents are registered on Agentverse and ASI:One-discoverable.
4. `README` documents how to run BOTH agents together and all env vars.
5. Graceful handling when the research agent is unavailable or returns no match.

### Out of scope (do not build these here)
- The research logic (Task 1), the PyMOL renderer (done), the Devin code-gen
  client `devin_client.py` (done), any frontend.
