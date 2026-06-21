import os
from dotenv import load_dotenv

# Load the .env sitting next to this script, regardless of the cwd it's run from.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

EXPECTED_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

from embeddings import EMBEDDING_MODEL, embed_query, embed_documents
from chunking import semantic_chunks

print(f"[1] Embedding model: {EMBEDDING_MODEL}")

# --- embeddings ---
q = embed_query("de novo protein design")
print(f"[2] embed_query -> dim={len(q)} (expected {EXPECTED_DIM})")
assert len(q) == EXPECTED_DIM, f"DIM MISMATCH: {len(q)} != {EXPECTED_DIM}"

docs = embed_documents(["alpha helix folding", "beta sheet topology"])
print(f"[3] embed_documents -> {len(docs)} vecs, dim={len(docs[0])}")
assert all(len(v) == EXPECTED_DIM for v in docs)

norm = sum(x * x for x in q) ** 0.5
print(f"[4] L2 norm = {norm:.4f} (should be ~1.0)")

# --- semantic chunking ---
text = (
    "De novo protein design creates new proteins from scratch. "
    "Diffusion models like RFdiffusion generate novel backbones. "
    "The weather in Paris was cold and rainy all week. "
    "Tourists still crowded the museums despite the storms. "
    "Sequence design then assigns amino acids to the backbone. "
    "AlphaFold validates whether the design will fold as intended."
)
chunks = semantic_chunks(text)
print(f"[5] semantic_chunks -> {len(chunks)} chunk(s):")
for i, c in enumerate(chunks):
    print(f"    [{i}] {c[:70]}...")
assert len(chunks) >= 1

print("SMOKE TEST PASSED")
