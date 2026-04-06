# qex

Lightweight Rust MCP server for semantic code search using BM25 (tantivy) + optional dense vector search (ONNX) + tree-sitter chunking.

- **GitHub**: https://github.com/us/qex
- **crates.io**: https://crates.io/crates/qex-mcp / https://crates.io/crates/qex-core

## Architecture

- `crates/qex-core/` - Core library: chunking, merkle, search, indexing
- `crates/qex-mcp/` - MCP server binary (stdio transport via rmcp)

## Build & Test

```bash
cargo test                              # BM25-only tests (41 tests)
cargo test --features dense             # Full tests including dense search (48 tests)
cargo test --features openai            # Tests with OpenAI embedder (50 tests)
cargo test --features "dense,openai"    # Both features (55 tests)
cargo build --release                   # BM25-only binary (~19 MB)
cargo build --release --features dense  # With dense vector search (~36 MB)
cargo build --release --features "dense,openai"  # All embedding backends
```

## Dense Vector Search (optional)

Uses snowflake-arctic-embed-s (33MB ONNX INT8, 384-dim, 512 token max) for semantic embeddings.

```bash
# Download model
scripts/download-model.sh
# Or via MCP tool: download_model

# Model stored at: ~/.qex/models/arctic-embed-s/
```

When model is available, search automatically uses hybrid BM25 + dense with Reciprocal Rank Fusion. Falls back to BM25-only if model not downloaded.

### Pluggable Embedding Backends

Configured via env vars:
- `QEX_EMBEDDING_PROVIDER`: "onnx" (default) or "openai"
- `QEX_ONNX_MODEL_DIR`: override ONNX model directory (default: ~/.qex/models/arctic-embed-s)
- `QEX_OPENAI_API_KEY` / `OPENAI_API_KEY`: API key for OpenAI provider
- `QEX_OPENAI_MODEL`: OpenAI model name (default: text-embedding-3-small)
- `QEX_OPENAI_BASE_URL`: Override API base URL (for compatible APIs)

The `Embedder` trait in `search/embedding.rs` abstracts over backends. `dense.rs` accepts `&mut dyn Embedder`.
Dimension mismatch between existing index and current embedder is detected via `dense_meta.json`.

### Dense feature deps
- `ort 2.0.0-rc.11` - ONNX Runtime (requires ndarray 0.17 to match ort's version)
- `usearch 2.24` - HNSW vector index
- `tokenizers 0.22` - HuggingFace tokenizer (needs `fancy-regex` feature)

### OpenAI feature deps
- `ureq 3` - Sync HTTP client (with `json` feature)

## MCP Integration

```bash
claude mcp add qex --scope user -- ~/.local/bin/qex
```

## Key Dependencies

- `tantivy 0.22` - BM25 full-text search
- `tree-sitter 0.24` - Code parsing (10 languages)
- `rmcp 0.17` - MCP server framework
- `ignore 0.4` - Gitignore-compatible file walking
- `rusqlite 0.32` - SQLite metadata (bundled)

## Conventions

- All logs go to stderr (stdout reserved for MCP JSON-RPC)
- Storage: `~/.qex/projects/{name}_{hash}/`
- Dense index: `~/.qex/projects/{name}_{hash}/dense/`
- rmcp uses `Parameters<T>` wrapper for tool params, `ErrorData` for errors
- schemars must use `rmcp::schemars::JsonSchema` (v1, not standalone 0.8)
- `#[cfg(feature = "dense")]` for ONNX-specific code paths
- `#[cfg(feature = "openai")]` for OpenAI embedder code
- `#[cfg(any(feature = "dense", feature = "openai"))]` for shared embedding trait module
- `session.run()` in ort 2.0 requires `&mut self` — encode methods are `&mut self`
