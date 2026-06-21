"""Semantic chunking with sentence-transformers (no LangChain).

Splits text on meaning shifts: embed sentences, then start a new chunk wherever
the cosine distance between consecutive sentences exceeds a percentile threshold.
This mirrors LangChain SemanticChunker's "percentile" strategy.
"""

import re

import numpy as np

from embeddings import get_embedder

_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _combine_sentences(sentences: list[str], buffer_size: int = 1) -> list[str]:
    """Combine each sentence with `buffer_size` neighbours on each side.

    Adding context reduces noise so the distance signal reflects real topic
    shifts rather than single-sentence quirks.
    """
    combined = []
    for i in range(len(sentences)):
        lo = max(0, i - buffer_size)
        hi = min(len(sentences), i + buffer_size + 1)
        combined.append(" ".join(sentences[lo:hi]))
    return combined


def semantic_chunks(
    text: str,
    breakpoint_percentile: float = 95.0,
    buffer_size: int = 1,
    min_sentences: int = 2,
) -> list[str]:
    """Split `text` into semantically coherent chunks."""
    sentences = _split_sentences(text)
    if len(sentences) <= min_sentences:
        return [text] if text.strip() else []

    combined = _combine_sentences(sentences, buffer_size)
    # Normalized embeddings -> cosine similarity is just the dot product.
    embeddings = get_embedder().encode(
        combined, normalize_embeddings=True, convert_to_numpy=True
    )

    similarities = np.sum(embeddings[:-1] * embeddings[1:], axis=1)
    distances = 1.0 - similarities

    threshold = np.percentile(distances, breakpoint_percentile)
    breakpoints = [i for i, d in enumerate(distances) if d > threshold]

    chunks = []
    start = 0
    for bp in breakpoints:
        # bp is the gap between sentence bp and bp+1 -> chunk ends at bp.
        chunks.append(" ".join(sentences[start : bp + 1]))
        start = bp + 1
    chunks.append(" ".join(sentences[start:]))
    return [c for c in chunks if c.strip()]
