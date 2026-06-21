"""Query the Redis paper index with optional metadata pre-filtering.

Example:
    python search.py "how does the model handle backbone generation?" \
        --year-min 2023 --source arxiv --k 5
"""

import argparse
import re
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

# A PDB ID is 4 chars: a leading digit 1-9 then three alphanumerics, e.g. 6M0J.
_PDB_RE = re.compile(r"\b[1-9][A-Za-z0-9]{3}\b")
# Context words that signal a nearby PDB accession code, used to cut down on
# false positives (years like "2020" also match the bare ID pattern).
_PDB_CONTEXT_RE = re.compile(
    r"(?:PDB|Protein Data Bank|accession (?:code|number|id)s?|deposited)"
    r"[^.\n]{0,80}?\b([1-9][A-Za-z0-9]{3})\b",
    re.IGNORECASE,
)


def extract_pdb_ids(text: str, require_context: bool = True) -> list[str]:
    """Return deduped, uppercased PDB IDs found in ``text``.

    By default only IDs sitting next to a context word ("PDB", "accession",
    etc.) are returned, which avoids matching 4-digit years. Set
    ``require_context=False`` to also accept any standalone ID that contains at
    least one letter (still excludes all-digit tokens like "2020").
    """
    found: list[str] = []
    seen: set[str] = set()

    def _add(code: str) -> None:
        code = code.upper()
        if code not in seen:
            seen.add(code)
            found.append(code)

    for m in _PDB_CONTEXT_RE.finditer(text):
        _add(m.group(1))

    if not require_context:
        for m in _PDB_RE.finditer(text):
            code = m.group(0)
            if any(c.isalpha() for c in code):
                _add(code)

    return found


def extract_pdb_ids_from_results(results: list[dict], **kwargs) -> list[str]:
    """Aggregate, dedupe and return PDB IDs across a list of search results."""
    seen: set[str] = set()
    ordered: list[str] = []
    for r in results:
        for code in extract_pdb_ids(r.get("content", ""), **kwargs):
            if code not in seen:
                seen.add(code)
                ordered.append(code)
    return ordered


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

    pdb_ids = extract_pdb_ids_from_results(results)
    if pdb_ids:
        print(f"\nPDB IDs found: {', '.join(pdb_ids)}")
    else:
        print("\nPDB IDs found: none")


if __name__ == "__main__":
    main()
