# redis_interactions

A small Redis-backed vector-search pipeline for research papers:

```
PDF  ->  extracted text  ->  semantic chunks  ->  EmbeddingGemma vectors  ->  Redis vector index  ->  search
```

| File | Purpose |
| --- | --- |
| `redis_client.py` | Shared, configured `redis-py` client + the `redis(s)://` URL RedisVL needs. |
| `redis_connect.py` | Minimal connectivity check (`SET`/`GET`). |
| `schema.py` | RedisVL vector-index schema (one JSON doc per chunk). |
| `embeddings.py` | EmbeddingGemma wrapper (document/query prompts, cached model). |
| `chunking.py` | Semantic chunking (splits text on meaning shifts). |
| `ingest.py` | Ingest one PDF or a directory of PDFs into the index. |
| `search.py` | Vector search with optional metadata pre-filtering. |
| `_smoke_test.py` | Verifies embeddings + chunking work end-to-end (no Redis needed). |
| `_conn_check.py` | Low-level RESP connectivity/auth probe (raw socket `AUTH`/`PING`/`SET`/`GET` with retries) to isolate network vs. auth vs. TLS problems. |

## Prerequisites

- Python 3.10+
- A reachable Redis instance with the **Query Engine / vector search** module (Redis Stack, Redis Cloud, or Redis 8+).
- A free [Hugging Face](https://huggingface.co/) account (EmbeddingGemma is a gated model — see step 3).

## Setup

### 1. Create a virtual environment and install dependencies

From the `redis_interactions/` folder:

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure your Redis credentials

Copy the example env file and fill in your connection details:

```powershell
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

Edit `.env`:

| Variable | Required | Notes |
| --- | --- | --- |
| `REDIS_HOST` | yes | Hostname of your Redis instance. |
| `REDIS_PORT` | yes | Port (often `6379`, or a custom port on Redis Cloud). |
| `REDIS_USERNAME` | no | Defaults to `default`. |
| `REDIS_PASSWORD` | yes* | Required for password-protected / managed Redis. |
| `REDIS_TLS` | no | Set `true` for managed Redis that requires TLS (`rediss://`). |
| `EMBEDDING_MODEL` | no | Defaults to `google/embeddinggemma-300m`. |
| `EMBEDDING_DIM` | no | Defaults to `768`. Must match the model and the index. |
| `REDIS_INDEX_NAME` | no | Defaults to `idx:papers`. |
| `REDIS_KEY_PREFIX` | no | Defaults to `chunk:`. |

> If you change `EMBEDDING_MODEL`, update `EMBEDDING_DIM` to match (EmbeddingGemma = 768, OpenAI `text-embedding-3-small` = 1536, `all-MiniLM-L6-v2` = 384).

### 3. Get the EmbeddingGemma model from Hugging Face

EmbeddingGemma (`google/embeddinggemma-300m`) is **gated**: you must accept Google's license and authenticate before the weights will download.

1. Sign in (or sign up) at [huggingface.co](https://huggingface.co/).
2. Visit the model page and accept the license:
   **https://huggingface.co/google/embeddinggemma-300m**
   Click *"Acknowledge license"* / *"Agree and access repository"*.
3. Create an access token at
   **https://huggingface.co/settings/tokens** (a `read` token is enough).
4. Authenticate locally (the `hf` CLI ships with `huggingface_hub`):

   ```powershell
   hf auth login
   ```

   Paste your token when prompted. (On older `huggingface_hub` versions use `huggingface-cli login`.) Alternatively, set the token via an environment variable instead of logging in:

   ```powershell
   $env:HF_TOKEN = "hf_xxxxxxxxxxxxxxxxx"   # Windows PowerShell
   # export HF_TOKEN=hf_xxxxxxxxxxxxxxxxx    # macOS / Linux
   ```

The model (~1.2 GB) is downloaded and cached on first use; subsequent runs load it from the local cache.

### 4. Verify the install

Embeddings + chunking (no Redis required — also triggers the first model download):

```powershell
python _smoke_test.py
```

Expected: `SMOKE TEST PASSED`.

Redis connectivity:

```powershell
python redis_connect.py   # prints: bar
```

## Usage

### Create the index

```powershell
python schema.py
```

### Ingest papers

```powershell
# A single PDF with metadata
python ingest.py path\to\paper.pdf --paper-id arxiv_2401_12345 `
    --title "De Novo Protein Design" --authors "Jane Doe,John Smith" `
    --year 2024 --doi 10.1234/abcd --source arxiv

# Every PDF in a directory (metadata inferred from filenames)
python ingest.py path\to\papers_dir\
```

### Search

```powershell
python search.py "how does the model handle backbone generation?" `
    --year-min 2023 --source arxiv --k 5
```

## Troubleshooting

- **`401`/`gated repo` error when loading the model** — you skipped step 3: accept the license on the model page and run `hf auth login`.
- **`REDIS_HOST is not set`** — copy `.env.example` to `.env` and fill in your credentials.
- **Connection timeouts** — run `python _conn_check.py` to tell apart network reachability, server liveness, and credentials. Intermittent timeouts/DNS failures usually point to a local firewall, VPN, or flaky network rather than a config problem; just retry.
- **TLS errors (`WRONG_VERSION_NUMBER`, SSL handshake failures)** — `REDIS_TLS` must match how your Redis instance is configured. Set `REDIS_TLS=true` only if the instance requires TLS (`rediss://`); leave it `false` for plaintext endpoints. Forcing the wrong value will fail or hang.
- **Dimension mismatch on ingest/search** — `EMBEDDING_DIM` in `.env` must match the model and the existing index; recreate the index (`python schema.py`) if you change models.
