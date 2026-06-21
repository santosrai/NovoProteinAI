"""Ingest PDF research papers into the Redis vector index.

Pipeline:  PDF -> extracted text -> semantic chunks -> embeddings -> index.load

Usage:
    python ingest.py path/to/paper.pdf --paper-id arxiv_2401_12345 \
        --title "De Novo Protein Design" --authors "Jane Doe,John Smith" \
        --year 2024 --doi 10.1234/abcd --source arxiv

    # or ingest every PDF in a directory (metadata inferred from filename)
    python ingest.py path/to/papers_dir/
"""

import argparse
import os
import re

from embeddings import embed_documents
from chunking import semantic_chunks
from schema import KEY_PREFIX, create_index

# Canonical section name -> regex of headings that map to it. Order matters:
# the first match wins. Covers the common layout of research papers.
_SECTION_PATTERNS = [
    ("abstract", r"abstract|summary"),
    ("introduction", r"introduction|background"),
    ("results", r"results"),
    ("discussion", r"discussion"),
    ("methods", r"methods|materials\s+and\s+methods|experimental(\s+procedures)?"),
    ("conclusion", r"conclusions?|concluding\s+remarks"),
    ("acknowledgements", r"acknowledge?ments"),
    ("references", r"references|bibliography"),
]

# A heading is a short line that is (optionally numbered and) exactly one of the
# section words above, e.g. "Methods", "2. Results", "Materials and Methods".
_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s+)?(?:" + "|".join(p for _, p in _SECTION_PATTERNS) + r")\s*:?\s*$",
    re.IGNORECASE,
)


def extract_text(pdf_path: str) -> str:
    """Extract text from a PDF, preserving line breaks for section detection.

    Prefers PyMuPDF with sorted (reading-order) extraction, which handles the
    two-column layout of journals like Nature far better than pypdf. Falls back
    to pypdf if PyMuPDF isn't installed.
    """
    try:
        import fitz  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            pages = [page.get_text("text", sort=True) for page in doc]
        text = "\n".join(pages)
    except ImportError:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # Re-join words split by end-of-line hyphenation: "pro-\ntein" -> "protein".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Collapse horizontal whitespace but keep newlines (needed for headings).
    return re.sub(r"[ \t]+", " ", text).strip()


def _classify_heading(line: str) -> str | None:
    """Return the canonical section name for a heading line, else None."""
    if not _HEADING_RE.match(line):
        return None
    lowered = line.lower()
    for name, pattern in _SECTION_PATTERNS:
        if re.search(pattern, lowered):
            return name
    return None


def extract_sections(text: str) -> list[tuple[str, str]]:
    """Split text into (section_name, section_text) pairs by heading lines.

    Text before the first detected heading is labelled "". If no headings are
    found at all (e.g. messy extraction), returns a single ("", text) pair so
    downstream chunking still works.
    """
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.split("\n"):
        name = _classify_heading(line.strip())
        if name:
            sections.append((name, []))
        else:
            sections[-1][1].append(line)

    result = [(name, "\n".join(lines).strip()) for name, lines in sections]
    result = [(name, body) for name, body in result if body]
    return result or [("", text)]


def build_records(chunked: list[tuple[str, str]], meta: dict) -> list[dict]:
    """Attach metadata + embeddings to each (section, chunk), for index.load.

    `chunked` is a list of (section_name, chunk_text). Embeddings are computed
    in a single batch for efficiency.
    """
    texts = [chunk for _, chunk in chunked]
    vectors = embed_documents(texts)
    records = []
    for i, ((section, chunk), vec) in enumerate(zip(chunked, vectors)):
        records.append(
            {
                "paper_id": meta["paper_id"],
                "title": meta.get("title", ""),
                "authors": meta.get("authors", []),
                "doi": meta.get("doi", ""),
                "year": meta.get("year", 0),
                "source": meta.get("source", ""),
                # Detected section wins; fall back to any value passed in meta.
                "section": section or meta.get("section", ""),
                "chunk_index": i,
                "content": chunk,
                "embedding": vec,
            }
        )
    return records


def ingest_pdf(pdf_path: str, meta: dict, index=None) -> int:
    """Ingest a single PDF; returns the number of chunks stored.

    Pass an existing `index` to avoid re-creating it per file in a batch.
    """
    if index is None:
        index = create_index()  # idempotent
    text = extract_text(pdf_path)
    if not text:
        print(f"  ! no extractable text in {pdf_path}, skipping")
        return 0

    # Chunk each section independently so chunks never straddle a section
    # boundary, and tag every chunk with its section.
    chunked: list[tuple[str, str]] = []
    for section, body in extract_sections(text):
        for chunk in semantic_chunks(body):
            chunked.append((section, chunk))

    records = build_records(chunked, meta)
    if not records:
        print(f"  ! no chunks produced from {pdf_path}, skipping")
        return 0

    # Stable per-chunk keys: {KEY_PREFIX}{paper_id}:{chunk_index}. The prefix
    # MUST match the index prefix or the index won't pick the documents up.
    index.load(
        records,
        id_field=None,
        keys=[f"{KEY_PREFIX}{meta['paper_id']}:{r['chunk_index']}" for r in records],
    )
    print(f"  loaded {len(records)} chunks from {os.path.basename(pdf_path)}")
    return len(records)


def _meta_from_filename(pdf_path: str) -> dict:
    """Minimal metadata when none is provided (uses the filename as paper_id)."""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    paper_id = re.sub(r"[^A-Za-z0-9_]+", "_", stem)
    return {"paper_id": paper_id, "title": stem, "source": "local"}


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest PDF papers into Redis.")
    p.add_argument("path", help="PDF file or directory of PDFs")
    p.add_argument("--paper-id")
    p.add_argument("--title", default="")
    p.add_argument("--authors", default="", help="comma-separated")
    p.add_argument("--doi", default="")
    p.add_argument("--year", type=int, default=0)
    p.add_argument("--source", default="")
    p.add_argument("--section", default="")
    args = p.parse_args()

    if os.path.isdir(args.path):
        pdfs = [
            os.path.join(args.path, f)
            for f in os.listdir(args.path)
            if f.lower().endswith(".pdf")
        ]
        index = create_index()  # create once, reuse across the batch
        total = 0
        for pdf in pdfs:
            try:
                total += ingest_pdf(pdf, _meta_from_filename(pdf), index=index)
            except Exception as exc:  # one bad PDF shouldn't abort the batch
                print(f"  ! failed to ingest {os.path.basename(pdf)}: {exc}")
        print(f"Done. {total} chunks from {len(pdfs)} PDFs.")
        return

    meta = {
        "paper_id": args.paper_id or _meta_from_filename(args.path)["paper_id"],
        "title": args.title,
        "authors": [a.strip() for a in args.authors.split(",") if a.strip()],
        "doi": args.doi,
        "year": args.year,
        "source": args.source,
        "section": args.section,
    }
    ingest_pdf(args.path, meta)


if __name__ == "__main__":
    main()
