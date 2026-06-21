"""Embedding model wrapper (EmbeddingGemma, open weights).

Uses a single shared sentence-transformers model so that both the semantic
chunker and the ingestion step reuse the same loaded model.

Swap EMBEDDING_MODEL / EMBEDDING_DIM (in .env) to use a different model.
"""

import os
from functools import lru_cache

from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "google/embeddinggemma-300m")


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    """Return a cached SentenceTransformer (loads the model once)."""
    return SentenceTransformer(EMBEDDING_MODEL)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a batch of chunk texts."""
    # normalize_embeddings=True -> unit vectors, required for COSINE.
    vectors = get_embedder().encode(texts, normalize_embeddings=True)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a single search query."""
    vector = get_embedder().encode(text, normalize_embeddings=True)
    return vector.tolist()


if __name__ == "__main__":
    vec = embed_query("de novo protein design")
    print(f"model={EMBEDDING_MODEL} dim={len(vec)}")
