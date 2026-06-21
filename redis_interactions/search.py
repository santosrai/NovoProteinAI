"""Query the Redis paper index with optional metadata pre-filtering.

Example:
    python search.py "how does the model handle backbone generation?" \
        --year-min 2023 --source arxiv --k 5
"""

import argparse
import sys

from redisvl.query import VectorQuery
from redisvl.query.filter import Num, Tag

try:  # package mode
    from .embeddings import embed_query
    from .schema import get_index
except ImportError:  # run directly as a script
    from embeddings import embed_query
    from schema import get_index

RETURN_FIELDS = ["content", "title", "paper_id", "section", "year", "source"]


def build_filter(source=None, paper_id=None, section=None, year_min=None):
    """Combine optional TAG/NUMERIC filters; applied before the vector search."""
    expr = None
    for f in (
        Tag("source") == source if source else None,
        Tag("paper_id") == paper_id if paper_id else None,
        Tag("section") == section if section else None,
        Num("year") >= year_min if year_min is not None else None,
    ):
        if f is not None:
            expr = f if expr is None else (expr & f)
    return expr


def search(question: str, k: int = 5, **filters) -> list[dict]:
    """Embed the question and run a filtered vector search."""
    index = get_index()
    query = VectorQuery(
        vector=embed_query(question),
        vector_field_name="embedding",
        return_fields=RETURN_FIELDS,
        num_results=k,
        filter_expression=build_filter(**filters),
    )
    return index.query(query)


def main() -> None:
    # Paper text often contains non-cp1252 Unicode (e.g. typographic spaces);
    # force UTF-8 so printing results doesn't crash on the Windows console.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="Vector search over ingested papers.")
    p.add_argument("question")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--source")
    p.add_argument("--paper-id")
    p.add_argument("--section")
    p.add_argument("--year-min", type=int)
    args = p.parse_args()

    results = search(
        args.question,
        k=args.k,
        source=args.source,
        paper_id=args.paper_id,
        section=args.section,
        year_min=args.year_min,
    )
    for i, r in enumerate(results, 1):
        score = r.get("vector_distance", "n/a")
        print(f"\n[{i}] {r.get('title')} ({r.get('year')})  dist={score}")
        print(f"    {r.get('content', '')[:300]}...")


if __name__ == "__main__":
    main()
