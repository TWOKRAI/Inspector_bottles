# Search Pipeline

## Overview

```
Query → Analysis → BM25 Search ──→ Fusion → Re-ranking → Results
                 → Dense Search ─↗ (optional)
```

## 1. Query Analysis

Every search query goes through analysis before hitting the engines.

**Tokenization** — Split on whitespace, punctuation, camelCase boundaries, and snake_case separators.

**Stop-word removal** — Common words (`the`, `a`, `is`, `in`, etc.) are stripped to reduce noise.

**Intent detection** — The query is classified into one of 6 intent categories:

| Intent | Trigger patterns | Effect |
|--------|-----------------|--------|
| Function | `function`, `fn`, `def`, `func`, `method`, `handler` | Boosts function/method chunks |
| Class | `class`, `struct`, `type`, `interface`, `trait`, `enum` | Boosts class/struct chunks |
| Error | `error`, `err`, `exception`, `panic`, `fail`, `bug` | Boosts error_handling tagged chunks |
| Config | `config`, `setting`, `env`, `option`, `flag` | Boosts configuration code |
| Test | `test`, `spec`, `assert`, `mock`, `fixture` | Reduces test penalty |
| API | `api`, `endpoint`, `route`, `handler`, `middleware`, `http` | Boosts API-related chunks |

**Synonym expansion** — 16 synonym pairs expand queries. Examples:
- `error` ↔ `err`, `exception`
- `function` ↔ `fn`, `func`, `def`
- `remove` ↔ `delete`
- `create` ↔ `new`, `init`

## 2. BM25 Search

Tantivy-based full-text search with a 14-field schema. Field boosts prioritize symbol names and paths over raw content.

| Field | Boost | Description |
|-------|-------|-------------|
| `name` | 5.0x | Symbol name |
| `path_tokens` | 2.0x | Tokenized file path |
| `docstring` | 1.5x | Documentation string |
| `tags` | 1.5x | Semantic tags |
| `content` | 1.0x | Full source text |
| `language` | — | Source language (filter) |
| `chunk_type` | — | Chunk type (filter) |
| `path` | — | Full file path (stored) |
| `start_line` / `end_line` | — | Line range (stored) |
| `decorators` | — | Decorators/attributes (stored) |
| `complexity` | — | Complexity score (stored) |

The query is applied as a disjunction across all boosted fields. Tantivy handles tokenization, stemming, and BM25 scoring internally.

## 3. Dense Vector Search (Optional)

Requires the `dense` feature flag and an embedding backend.

**Pluggable Embedder** — The `Embedder` trait abstracts over embedding backends. Two implementations are available:

| Backend | Feature Flag | Dimensions | Latency | Dependencies |
|---------|-------------|-----------|---------|--------------|
| ONNX Runtime (snowflake-arctic-embed-s) | `dense` | 384 | ~15ms/batch | Local, zero cloud |
| OpenAI API (text-embedding-3-small) | `dense,openai` | 1536 | ~200ms/batch | Requires API key |

The backend is selected via `QEX_EMBEDDING_PROVIDER` env var (`onnx` or `openai`).

**Embedding** — Queries and chunks are embedded into dense vectors via the active backend. Chunks are batched (8 per batch for ONNX, 100 per batch for OpenAI) during indexing. All vectors are L2-normalized to unit length.

**HNSW Index** — usearch builds an approximate nearest neighbor index. Cosine similarity is used for retrieval.

**Dimension Guard** — When the embedding provider or model changes, `dense_meta.json` detects the mismatch and triggers a full re-index to prevent mixing vectors from different embedding spaces.

**Model (ONNX)** — Snowflake Arctic Embed S (33 MB, INT8 quantized). Stored at `~/.qex/models/arctic-embed-s/`.

**API (OpenAI)** — Synchronous HTTP via ureq with configurable timeouts (connect: 10s, response: 60s), SSRF protection, API key sanitization, and typed exponential backoff retry (429/5xx/timeout).

## 4. Reciprocal Rank Fusion

When both BM25 and dense results are available, they're merged using RRF:

```
score = Σ 1/(k + rank)    where k = 60
```

Each result gets a fusion score based on its rank in each engine's result list. Results appearing in both lists get higher combined scores.

## 5. Multi-Factor Re-ranking

After fusion (or after BM25 alone), results go through multi-factor re-ranking:

**File type boost:**

| Category | Multiplier |
|----------|-----------|
| Source code (.rs, .py, .ts, .go, etc.) | 1.0x |
| Config files (.toml, .json, .yaml) | 0.9x |
| Documentation (.md) | 0.8x |
| Test files | 0.7x |
| Vendor/generated | 0.3x |

**Chunk type boost** — When query intent matches chunk type (e.g., "class" intent + class chunk = 1.3x).

**Name match boost** — Exact name match gives 1.5x boost.

**Path boost** — Query terms appearing in file path add a boost.

**Tag boost** — When query intent matches chunk tags (e.g., "error" intent + `error_handling` tag).

**Docstring boost** — Chunks with docstrings get a small boost.

**Complexity penalty** — Very complex chunks get slightly penalized.

**Translation dedup** — Duplicate i18n/locale files are deduplicated.

## 6. Score Thresholding

Low-relevance results are filtered out:

- **Minimum threshold**: 12% of top result score
- **Knee detection**: If there's a sharp score drop between consecutive results, results below the knee are cut
