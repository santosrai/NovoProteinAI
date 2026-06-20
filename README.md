# NovoProteinAI

Turn a plain-English vaccine/therapeutic goal into a real protein target, its
epitope, and known binders — then visualize it.

## Research agent (Fetch.ai / ASI:One)

`research_agent.py` is a Fetch.ai uAgent that takes a goal like
`"build a vaccine for COVID"` and returns a structured result sourced from public
biology databases (PubMed, RCSB PDB, IEDB) with goal-parsing and explanations
drafted by ASI:One. Its output feeds directly into `render_image()` in
`visualize.py`.

### Output contract

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

`pdb_id` (str), `chain` (str) and `epitope_residues` (list[int]) are always
present and validated against the live PDB before returning. `binder_pdb_ids`
may be empty. On a no-match goal the structural fields are empty and
`explanation` describes the problem (the agent never crashes on bad input).

### Setup

```bash
pip install -r requirements.txt
# PyMOL (for rendering) is installed separately, e.g.:
#   conda install -c conda-forge pymol-open-source
```

### Environment variables

| Var | Purpose | Required |
| --- | --- | --- |
| `ASI_ONE_API_KEY` | ASI:One LLM (goal → search terms, explanation). Without it the pipeline falls back to a keyword heuristic and still runs. | recommended |
| `AGENT_SEED` | Fixed seed → stable agent identity/address. | recommended |
| `AGENTVERSE_API_KEY` | Agentverse mailbox registration. | for Agentverse |
| `ASI_ONE_BASE_URL` | Override ASI:One base URL (default `https://api.asi1.ai/v1`). | no |
| `ASI_ONE_MODEL` | ASI:One model (default `asi1-mini`). | no |

### Run as a CLI (research + render)

```bash
# Print the JSON contract for a goal
python research_agent.py --goal "build a vaccine for COVID"

# Also render the result to a PNG via visualize.render_image()
python research_agent.py --goal "build a vaccine for COVID" --render --out target.png
```

### Run as a Fetch.ai agent (ASI:One discoverable)

```bash
export ASI_ONE_API_KEY=...        # ASI:One LLM
export AGENT_SEED=...             # stable identity
export AGENTVERSE_API_KEY=...     # mailbox registration
python research_agent.py
```

This starts the agent named `novoprotein-research`, includes the
[chat protocol](https://uagents.fetch.ai/docs/guides/chat_protocol) so it's
ASI:One-compatible, and connects via mailbox so it's discoverable on Agentverse.
Send it a chat message (e.g. `"build a vaccine for COVID"`) and it replies with
the JSON contract above.

## Visualization

`visualize.py` renders a target/epitope/binder scene with PyMOL:

```bash
python visualize.py            # renders target.png (COVID spike demo)
python visualize.py --window   # interactive PyMOL window
```
