"""High-level PubMed research pipeline for NovoProteinAI.

Ties the package together end to end:

    topic -> PubMed search -> fetch & parse (full text when open-access)
          -> ingest into the shared Redis vector index
          -> semantic search for grounded, accurate answers

Public entry points (re-exported from the package ``__init__``):
    * ``search_and_ingest(topic, ...)``  – fetch + ingest, return a summary
    * ``research_topic(topic, ...)``      – the above, then semantic search

CLI:
    python research_paper_interactions/research_paper_interactions.py \
        "TNF-alpha inhibitor structure" --max-papers 5 --k 5
"""

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:  # package mode
    from . import pubmed
    from .ingest import ingest_papers
except ImportError:  # run directly as a script
    import pubmed
    from ingest import ingest_papers

# Retrieval reuses the existing shared search so PubMed and PDF papers are
# queried through one path.
from redis_interactions.schema import create_index
from redis_interactions.search import search as _vector_search


def search_and_ingest(
    topic: str, max_papers: int = 5, prefer_fulltext: bool = True
) -> dict:
    """Search PubMed for `topic`, fetch/parse the papers, and ingest them.

    Returns ``{"topic", "pmids", "ingested": [...], "total_chunks"}`` where each
    ``ingested`` entry reports the paper id, title, source (pmc full text vs
    pubmed abstract) and the number of chunks stored.
    """
    pmids = pubmed.esearch(topic, retmax=max_papers)
    if not pmids:
        return {"topic": topic, "pmids": [], "ingested": [], "total_chunks": 0}

    papers = pubmed.fetch_papers(pmids, prefer_fulltext=prefer_fulltext)
    index = create_index()  # idempotent; create once and reuse across the batch
    ingested = ingest_papers(papers, index=index)
    return {
        "topic": topic,
        "pmids": pmids,
        "ingested": ingested,
        "total_chunks": sum(item.get("chunks", 0) for item in ingested),
    }


def research_topic(
    topic: str,
    question: str | None = None,
    max_papers: int = 5,
    k: int = 5,
    prefer_fulltext: bool = True,
) -> dict:
    """Ingest papers for `topic`, then semantically search the index.

    `question` defaults to `topic`. Returns the ingestion summary plus the
    top-`k` matching chunks (title, paper_id, section, year, source, content).
    """
    ingestion = search_and_ingest(
        topic, max_papers=max_papers, prefer_fulltext=prefer_fulltext
    )
    rows = _vector_search(question or topic, k=k)
    results = [
        {
            "title": r.get("title", ""),
            "paper_id": r.get("paper_id", ""),
            "section": r.get("section", ""),
            "year": r.get("year", ""),
            "source": r.get("source", ""),
            "content": r.get("content", ""),
        }
        for r in rows
    ]
    return {"ingestion": ingestion, "results": results}


def main() -> None:
    # Paper text contains non-cp1252 Unicode; force UTF-8 so printing on the
    # Windows console doesn't crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(
        description="Search PubMed, ingest into Redis, and semantically query."
    )
    p.add_argument("topic", help="topic / search term for PubMed")
    p.add_argument("--question", help="question to answer (defaults to the topic)")
    p.add_argument("--max-papers", type=int, default=5)
    p.add_argument("--k", type=int, default=5, help="number of chunks to return")
    p.add_argument(
        "--abstract-only",
        action="store_true",
        help="skip PMC full text; ingest abstracts only",
    )
    args = p.parse_args()

    out = research_topic(
        args.topic,
        question=args.question,
        max_papers=args.max_papers,
        k=args.k,
        prefer_fulltext=not args.abstract_only,
    )

    ing = out["ingestion"]
    print(f"\nIngested {ing['total_chunks']} chunks from {len(ing['ingested'])} papers:")
    for item in ing["ingested"]:
        tag = item.get("source", "?")
        err = f"  ERROR: {item['error']}" if item.get("error") else ""
        print(f"  [{tag}] {item.get('title') or item.get('paper_id')} "
              f"-> {item.get('chunks', 0)} chunks{err}")

    print(f"\nTop {len(out['results'])} results for "
          f"'{args.question or args.topic}':")
    for i, r in enumerate(out["results"], 1):
        print(f"\n[{i}] {r['title']} ({r['year']}) [{r['source']}/{r['section']}]")
        print(f"    {r['content'][:300]}...")


if __name__ == "__main__":
    main()
