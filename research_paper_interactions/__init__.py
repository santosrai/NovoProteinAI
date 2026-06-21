"""PubMed -> Redis research pipeline for NovoProteinAI.

Searches PubMed for a topic, fetches and parses each paper directly from NCBI
E-utilities XML (full text from PMC when open-access, abstract otherwise — no
PDF download), ingests the text into the shared Redis vector index, and answers
questions with semantic search.

The package exposes plain functions; the agent wraps them with a ``@tool``
decorator (see ``src/agent_graph.py``).

Public API:
    search_and_ingest(topic, max_papers=5, prefer_fulltext=True)
    research_topic(topic, question=None, max_papers=5, k=5)
    pubmed.esearch / pubmed.fetch_paper / pubmed.fetch_papers
    ingest_paper / ingest_papers
"""

import importlib

from . import pubmed  # lightweight (requests + stdlib only)

__all__ = [
    "pubmed",
    "ingest_paper",
    "ingest_papers",
    "search_and_ingest",
    "research_topic",
]

# Lazily expose the ingest/orchestration API so that merely importing the
# package (e.g. to use ``pubmed``) doesn't pull in the heavy redisvl /
# sentence-transformers stack. The deps load only when these names are accessed.
_LAZY = {
    "ingest_paper": ("ingest", "ingest_paper"),
    "ingest_papers": ("ingest", "ingest_papers"),
    "search_and_ingest": ("research_paper_interactions", "search_and_ingest"),
    "research_topic": ("research_paper_interactions", "research_topic"),
}


def __getattr__(name):  # PEP 562 module-level lazy attribute access
    if name in _LAZY:
        module_name, attr = _LAZY[name]
        module = importlib.import_module(f".{module_name}", __name__)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
