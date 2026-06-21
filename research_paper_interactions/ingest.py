"""Ingest parsed PubMed/PMC papers into the shared Redis vector index.

This deliberately reuses the existing ``redis_interactions`` pipeline so that
papers fetched from PubMed land in the SAME index as PDF-ingested papers and are
searchable with the same ``redis_interactions.search.search`` (and the agent's
``search_papers`` tool):

    parsed sections -> semantic_chunks -> build_records (embeddings) -> index.load

A parsed paper is the dict produced by ``pubmed.fetch_paper``:
    {"meta": {paper_id, title, authors, doi, year, source, ...},
     "sections": [(section_name, text), ...]}
"""

import os
import sys

# Make the repo root importable so ``redis_interactions`` resolves whether this
# module is imported as part of a package or run directly as a script.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from redis_interactions.chunking import semantic_chunks
from redis_interactions.ingest import build_records
from redis_interactions.schema import KEY_PREFIX, create_index

# Only these metadata keys are part of the index schema; pubmed adds extras
# (pmid, pmcid) that build_records would otherwise ignore anyway.
_META_KEYS = ("paper_id", "title", "authors", "doi", "year", "source", "section")


def _chunk_sections(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Semantic-chunk each section independently, tagging chunks with the section.

    Chunking per section (rather than over the concatenated text) keeps chunks
    from straddling a section boundary and preserves the section tag for
    metadata filtering.
    """
    chunked: list[tuple[str, str]] = []
    for section, body in sections:
        for chunk in semantic_chunks(body):
            chunked.append((section, chunk))
    return chunked


def ingest_paper(paper: dict, index=None) -> int:
    """Ingest one parsed paper; returns the number of chunks stored.

    Pass an existing `index` to avoid re-creating it per paper in a batch.
    """
    sections = paper.get("sections") or []
    meta = {k: paper["meta"].get(k) for k in _META_KEYS if k in paper["meta"]}
    if not sections or not meta.get("paper_id"):
        return 0

    if index is None:
        index = create_index()  # idempotent

    chunked = _chunk_sections(sections)
    records = build_records(chunked, meta)
    if not records:
        return 0

    # Stable per-chunk keys (must use the index prefix or the index won't see
    # them). Re-ingesting the same paper overwrites its chunks rather than
    # duplicating them.
    index.load(
        records,
        id_field=None,
        keys=[f"{KEY_PREFIX}{meta['paper_id']}:{r['chunk_index']}" for r in records],
    )
    return len(records)


def ingest_papers(papers: list[dict], index=None) -> list[dict]:
    """Ingest a batch of parsed papers; returns a per-paper summary list.

    One failing paper never aborts the batch.
    """
    if index is None:
        index = create_index()
    summary = []
    for paper in papers:
        meta = paper.get("meta", {})
        try:
            n_chunks = ingest_paper(paper, index=index)
        except Exception as exc:  # noqa: BLE001 - keep going on a bad paper
            summary.append(
                {"paper_id": meta.get("paper_id"), "chunks": 0, "error": str(exc)}
            )
            continue
        summary.append(
            {
                "paper_id": meta.get("paper_id"),
                "pmid": meta.get("pmid"),
                "title": meta.get("title"),
                "source": meta.get("source"),
                "chunks": n_chunks,
            }
        )
    return summary
