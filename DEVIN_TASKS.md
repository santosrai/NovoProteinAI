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
- The Claude conversation layer, the PyMOL renderer (already done), any frontend.
