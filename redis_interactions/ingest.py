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

from pypdf import PdfReader

from embeddings import embed_documents
from chunking import semantic_chunks
from schema import create_index


def extract_text(pdf_path: str) -> str:
    """Concatenate text from every page of a PDF."""
    reader = PdfReader(pdf_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    # Collapse runaway whitespace that PDF extraction tends to produce.
    return re.sub(r"[ \t]+", " ", text).strip()


def build_records(chunks: list[str], meta: dict) -> list[dict]:
    """Attach metadata + embeddings to each chunk, ready for index.load."""
    vectors = embed_documents(chunks)
    records = []
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        records.append(
            {
                "paper_id": meta["paper_id"],
                "title": meta.get("title", ""),
                "authors": meta.get("authors", []),
                "doi": meta.get("doi", ""),
                "year": meta.get("year", 0),
                "source": meta.get("source", ""),
                "section": meta.get("section", ""),
                "chunk_index": i,
                "content": chunk,
                "embedding": vec,
            }
        )
    return records


def ingest_pdf(pdf_path: str, meta: dict) -> int:
    """Ingest a single PDF; returns the number of chunks stored."""
    index = create_index()  # idempotent
    text = extract_text(pdf_path)
    if not text:
        print(f"  ! no extractable text in {pdf_path}, skipping")
        return 0
    chunks = semantic_chunks(text)
    records = build_records(chunks, meta)

    # Stable per-chunk keys: chunk:{paper_id}:{chunk_index}
    index.load(
        records,
        id_field=None,
        keys=[f"chunk:{meta['paper_id']}:{r['chunk_index']}" for r in records],
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
        total = 0
        for pdf in pdfs:
            total += ingest_pdf(pdf, _meta_from_filename(pdf))
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
