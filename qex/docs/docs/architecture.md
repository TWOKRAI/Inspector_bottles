# Architecture

## System Overview

```
┌─────────────────────────────────────────────┐
│              MCP Client                      │
│  Claude Code  │  Zed  │  Any MCP Client     │
└───────────────┴───────┴─────────────────────┘
                    │
              stdio JSON-RPC
                    │
┌───────────────────┴───────────────────┐
│           qex-mcp (binary)            │
│  server.rs → tools.rs → config.rs     │
└───────────────────┬───────────────────┘
                    │
┌───────────────────┴───────────────────┐
│           qex-core (library)          │
│                                       │
│  ┌─────────┐  ┌──────────┐  ┌──────┐ │
│  │ chunk/  │  │ search/  │  │index/│ │
│  │ tree-   │→ │ bm25     │  │incre-│ │
│  │ sitter  │  │ dense    │  │mental│ │
│  │ 10 langs│  │ hybrid   │  │      │ │
│  └─────────┘  │ ranking  │  └──────┘ │
│               │ query    │  ┌──────┐ │
│               └──────────┘  │merkle│ │
│                             │ DAG  │ │
│                             └──────┘ │
└───────────────────────────────────────┘
```

## Crate Structure

The project is a Cargo workspace with two crates:

**qex-core** — Core library. All indexing, search, and change detection logic.

**qex-mcp** — Binary. MCP server that wraps qex-core with stdio JSON-RPC transport via `rmcp`.

## Layers

### 1. MCP Server (`qex-mcp/`)

Entry point. Tokio async runtime with `rmcp` stdio transport. Exposes 5 MCP tools. All logs go to stderr (stdout is reserved for MCP JSON-RPC).

- `main.rs` — Async entry, transport setup
- `server.rs` — Tool handler implementations (index, search, status, clear, download)
- `tools.rs` — JSON Schema parameter definitions via `schemars`
- `config.rs` — CLI argument parsing via `clap`

### 2. Chunking Engine (`qex-core/chunk/`)

Tree-sitter based code parsing. Each source file is parsed into an AST, then walked to extract semantic code chunks.

- `tree_sitter.rs` — Core AST traversal engine
- `multi_language.rs` — Language router with parallel chunking via `rayon`
- `languages/` — 10 language-specific implementations + markdown

Each chunk (`CodeChunk`) contains:

| Field | Description |
|-------|-------------|
| `name` | Symbol name (function/class/method name) |
| `content` | Full source text |
| `chunk_type` | Function, Method, Class, Struct, Trait, Interface, Enum, Impl, Macro, Module, Section, Other |
| `path` | File path |
| `start_line` / `end_line` | Line range |
| `language` | Source language |
| `tags` | Semantic tags (async, auth, database, error_handling, test, etc.) |
| `complexity` | Complexity score |
| `docstring` | Extracted documentation |
| `decorators` | Python decorators, Rust attributes, etc. |

### 3. Search Engines (`qex-core/search/`)

Dual-engine architecture with fusion and re-ranking.

- `bm25.rs` — Tantivy BM25 index with 14-field schema and field-level boosts
- `dense.rs` — usearch HNSW vector index (feature: `dense`). Accepts `&mut dyn Embedder` for provider-agnostic embedding
- `embedding.rs` — `Embedder` trait definition, `EmbedderInfo` metadata, `load_embedder()` factory, ONNX `EmbeddingModel` backend (feature: `dense|openai`)
- `openai_embedder.rs` — OpenAI API embedding backend with retry, timeout, SSRF protection, API key sanitization (feature: `openai`)
- `hybrid.rs` — Reciprocal Rank Fusion to merge BM25 + dense results (feature: `dense`)
- `ranking.rs` — Multi-factor re-ranking (file type, chunk type, name match, path, tags, complexity)
- `query.rs` — Query analysis (tokenization, intent detection, synonym expansion, stop-word removal)

### 4. Incremental Indexer (`qex-core/index/`)

Manages the indexing lifecycle with three modes:

| Mode | When | Behavior |
|------|------|----------|
| Full | First index or force flag | Walk all files, chunk, index everything |
| Incremental | Merkle snapshot exists, changes detected | Only re-index added/modified files, remove deleted |
| Skip | Snapshot valid, no changes | Return immediately (<100ms) |

### 5. Merkle DAG (`qex-core/merkle/`)

SHA-256 hash tree for fast change detection.

- Each file is hashed to a leaf node
- Directory hashes are derived from children
- Root hash comparison gives O(1) "anything changed?" check
- File-level diff identifies exactly which files were added, deleted, or modified
- Snapshots are persisted to disk and checked for staleness (5-minute TTL)

### 6. File Walker (`qex-core/ignore.rs`)

Uses the `ignore` crate for `.gitignore`-compatible traversal. 50+ default ignore patterns for common non-source directories and files (`node_modules`, `target`, `.git`, vendor dirs, binary files, etc.).
