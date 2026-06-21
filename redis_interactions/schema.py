"""Redis vector index schema for ingested research papers.

One JSON document is stored per *chunk* (not per paper), so each retrievable
unit carries its own embedding plus the parent paper's metadata for filtering.

Key naming: chunk:{paper_id}:{chunk_index}
"""

import os

from redisvl.index import SearchIndex

try:  # package mode
    from .redis_client import get_redis_url
except ImportError:  # run directly as a script
    from redis_client import get_redis_url

# Embedding dimensionality MUST match the model that produced the vectors.
#   EmbeddingGemma (google/embeddinggemma-300m) -> 768 (or 512/256/128 via MRL)
#   OpenAI text-embedding-3-small               -> 1536
#   sentence-transformers all-MiniLM-L6-v2      -> 384
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
INDEX_NAME = os.getenv("REDIS_INDEX_NAME", "idx:papers")
KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "chunk:")

# Python-dictionary schema (the same structure RedisVL accepts as YAML).
SCHEMA_DICT = {
    "index": {
        "name": INDEX_NAME,
        "prefix": KEY_PREFIX,
        "storage_type": "json",
    },
    "fields": [
        # Free-text body of the chunk -> enables keyword + hybrid search.
        {"name": "content", "type": "text"},
        {"name": "title", "type": "text"},
        # Exact-match filters.
        {"name": "section", "type": "tag"},
        {"name": "paper_id", "type": "tag"},
        {"name": "authors", "type": "tag"},
        {"name": "doi", "type": "tag"},
        {"name": "source", "type": "tag"},
        # Numeric filters / sorting.
        {"name": "year", "type": "numeric", "attrs": {"sortable": True}},
        {"name": "chunk_index", "type": "numeric"},
        # The embedding vector itself.
        {
            "name": "embedding",
            "type": "vector",
            "attrs": {
                "dims": EMBEDDING_DIM,
                "algorithm": "hnsw",
                "datatype": "float32",
                "distance_metric": "cosine",
            },
        },
    ],
}


def get_index() -> SearchIndex:
    """Return a RedisVL SearchIndex bound to the live Redis connection."""
    return SearchIndex.from_dict(SCHEMA_DICT, redis_url=get_redis_url())


def create_index(overwrite: bool = False) -> SearchIndex:
    """Create the index in Redis (idempotent unless overwrite=True)."""
    index = get_index()
    index.create(overwrite=overwrite, drop=False)
    print(f"Index '{INDEX_NAME}' ready (dims={EMBEDDING_DIM}, prefix='{KEY_PREFIX}').")
    return index


if __name__ == "__main__":
    create_index()
