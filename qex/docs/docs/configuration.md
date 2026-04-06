# Configuration

## CLI Arguments

```
qex [OPTIONS]

Options:
  -v, --verbose    Enable verbose debug logging
  -h, --help       Print help
  -V, --version    Print version
```

qex has minimal configuration. It runs as a stdio MCP server with no config files. All behavior is controlled through MCP tool parameters.

## Feature Flags

Build-time feature flags control which search engines and embedding backends are available:

| Flag | Default | Binary Size | Description |
|------|---------|-------------|-------------|
| (none) | on | ~19 MB | BM25-only search via Tantivy |
| `dense` | off | ~36 MB | BM25 + dense vector search via ONNX Runtime + HNSW |
| `openai` | off | ~20 MB | OpenAI API embedding support via ureq |
| `dense,openai` | off | ~37 MB | All embedding backends |

```bash
# BM25-only (recommended for most use cases)
cargo build --release

# BM25 + dense (local ONNX embeddings)
cargo build --release --features dense

# BM25 + OpenAI embeddings
cargo build --release --features openai

# All backends
cargo build --release --features "dense,openai"
```

> **Note:** The `dense` feature is required for the HNSW vector index (usearch). To use OpenAI embeddings for dense search, you need both `dense` and `openai` features enabled.

## Storage

All data is stored under `~/.qex/`:

```
~/.qex/
├── projects/           # Per-project index data
│   └── {name}_{hash}/
│       ├── project_info.json
│       ├── tantivy/
│       ├── dense/          # Only with dense feature
│       ├── snapshot.json
│       ├── snapshot_metadata.json
│       └── stats.json
└── models/             # Embedding models (dense feature only)
    └── arctic-embed-s/
```

Project directories use a hash suffix derived from the absolute path, preventing collisions when multiple projects share the same directory name.

## Default Ignore Patterns

qex respects `.gitignore` rules and also applies 50+ built-in ignore patterns:

**Directories:**
`node_modules`, `target`, `build`, `dist`, `out`, `.next`, `.nuxt`, `vendor`, `third_party`, `.venv`, `__pycache__`, `.git`, `.svn`, `.hg`, `.idea`, `.vscode`, `.vs`, `coverage`, `.cache`, `.turbo`, `tmp`, `.bundle`, `.gradle`, `pods`

**Files:**
Images (`.png`, `.jpg`, `.gif`, `.svg`, `.ico`, `.webp`), fonts (`.woff`, `.woff2`, `.ttf`, `.eot`), archives (`.zip`, `.tar`, `.gz`), compiled objects (`.o`, `.so`, `.dylib`, `.dll`), lock files, minified files (`.min.js`, `.min.css`), source maps (`.map`)

## Embedding Backends

QEX supports pluggable embedding backends via the `Embedder` trait. The active backend is selected by the `QEX_EMBEDDING_PROVIDER` environment variable.

### ONNX Runtime (default)

Local inference, zero cloud dependencies. Requires the `dense` feature flag.

| Property | Value |
|----------|-------|
| Model | Snowflake Arctic Embed S |
| Format | ONNX (INT8 quantized) |
| Size | 33 MB |
| Dimensions | 384 |
| Location | `~/.qex/models/arctic-embed-s/` |
| Download | Via `download_model` MCP tool or `scripts/download-model.sh` |

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `QEX_EMBEDDING_PROVIDER` | `onnx` | Set to `onnx` or omit |
| `QEX_ONNX_MODEL_DIR` | `~/.qex/models/arctic-embed-s` | Override model directory (supports `~` expansion) |

### OpenAI API

Cloud-based embeddings via the OpenAI embeddings API. Requires the `openai` feature flag. Works with any OpenAI-compatible endpoint (OpenAI, Azure, Ollama, LiteLLM, etc.).

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `QEX_EMBEDDING_PROVIDER` | — | Set to `openai` |
| `QEX_OPENAI_API_KEY` | — | API key (also reads `OPENAI_API_KEY` as fallback) |
| `QEX_OPENAI_MODEL` | `text-embedding-3-small` | Embedding model name |
| `QEX_OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL |
| `QEX_OPENAI_DIMENSIONS` | auto-detected | Override dimensions for unknown models |

**Known model dimensions (auto-detected):**

| Model | Dimensions |
|-------|-----------|
| `text-embedding-3-small` | 1536 |
| `text-embedding-3-large` | 3072 |
| `text-embedding-ada-002` | 1536 |
| Other | Set `QEX_OPENAI_DIMENSIONS` (defaults to 1536) |

**Security:**
- **SSRF protection**: Base URLs must use HTTPS. Plain HTTP is only allowed for localhost/127.0.0.1/[::1] (for local proxies and Ollama).
- **API key sanitization**: Error messages never contain API keys or authorization headers. The `sk-` prefix pattern is also filtered.
- **Typed retry**: Exponential backoff (1s, 2s, 4s) with max 3 attempts on HTTP 429 (rate limit), 5xx (server error), timeouts, and connection failures. Uses `ureq::Error` variant matching, not string matching.

**Example configurations:**

```bash
# OpenAI (default)
export QEX_EMBEDDING_PROVIDER=openai
export QEX_OPENAI_API_KEY=sk-...

# Ollama (local)
export QEX_EMBEDDING_PROVIDER=openai
export QEX_OPENAI_API_KEY=unused
export QEX_OPENAI_BASE_URL=http://localhost:11434/v1
export QEX_OPENAI_MODEL=nomic-embed-text
export QEX_OPENAI_DIMENSIONS=768

# Azure OpenAI
export QEX_EMBEDDING_PROVIDER=openai
export QEX_OPENAI_API_KEY=your-azure-key
export QEX_OPENAI_BASE_URL=https://your-resource.openai.azure.com/openai/deployments/text-embedding-3-small
```

### Dimension Mismatch Guard

When the embedding provider or model changes between indexing runs, QEX detects the mismatch via `dense_meta.json` (stored alongside the dense index). This file records:

```json
{"provider":"onnx","dimensions":384,"model_name":"snowflake-arctic-embed-s"}
```

If any of these fields differ from the current embedder, the dense index is automatically rebuilt from scratch. This prevents silent search quality degradation from mismatched vector spaces.

## Merkle Snapshot TTL

Snapshots older than **5 minutes** trigger a re-check on the next `index_codebase` or `search_code` call. This ensures the index stays reasonably fresh without constant filesystem scanning.

## Dependencies

### BM25 Mode (Default)

| Crate | Version | Purpose |
|-------|---------|---------|
| tantivy | 0.22 | BM25 full-text search |
| tree-sitter | 0.24 | Code parsing (10+ language grammars) |
| rmcp | 0.17 | MCP server framework |
| rusqlite | 0.32 | SQLite metadata (bundled) |
| ignore | 0.4 | Gitignore-compatible file walking |
| rayon | 1.10 | Parallel chunking |
| sha2 | 0.10 | Merkle DAG hashing |
| clap | 4 | CLI argument parsing |

### Dense Mode (Additional)

| Crate | Version | Purpose |
|-------|---------|---------|
| ort | 2.0.0-rc.11 | ONNX Runtime |
| ndarray | 0.16 | Tensor operations |
| usearch | 2.24 | HNSW vector index |
| tokenizers | 0.22 | HuggingFace tokenizer |

### OpenAI Mode (Additional)

| Crate | Version | Purpose |
|-------|---------|---------|
| ureq | 3 | Synchronous HTTP client (with `json` feature) |
