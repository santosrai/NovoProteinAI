"""Semantic chunking with sentence-transformers (no LangChain).

Splits text on meaning shifts: embed sentences, then start a new chunk wherever
the cosine distance between consecutive sentences exceeds a percentile threshold.
This mirrors LangChain SemanticChunker's "percentile" strategy.
"""

import re

import numpy as np

from embeddings import get_embedder

# Split on .?! + whitespace, but ONLY when the next token starts a new sentence
# (a capital letter or an opening paren). This avoids the common scientific-text
# false splits: decimals ("0.5 was"), figure refs ("Fig. 3"), and abbreviations
# whose period is followed by a lowercase word ("e.g. the", "et al. found").
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+(?=[A-Z(\[])")


def _split_sentences(text: str) -> list[str]:
    # Treat newlines as soft spaces so PDF line wrapping doesn't break sentences.
    text = re.sub(r"\s*\n\s*", " ", text)
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _enforce_max_size(chunks: list[str], max_chars: int) -> list[str]:
    """Split any chunk longer than `max_chars` on sentence boundaries.

    A single semantic chunk can exceed the embedding model's context window;
    truncation there silently drops content, so we cap chunk size up front.
    """
    out: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            out.append(chunk)
            continue
        current = ""
        for sentence in _split_sentences(chunk):
            if current and len(current) + len(sentence) + 1 > max_chars:
                out.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            out.append(current)
    return out


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
    max_chars: int = 2000,
) -> list[str]:
    """Split `text` into semantically coherent chunks (each <= `max_chars`)."""
    sentences = _split_sentences(text)
    if len(sentences) <= min_sentences:
        return _enforce_max_size([text], max_chars) if text.strip() else []

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
    return _enforce_max_size([c for c in chunks if c.strip()], max_chars)
