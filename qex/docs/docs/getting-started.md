# qex

Semantic code search MCP server for Claude Code and other MCP clients.

Claude Code defaults to `grep` + `glob` for codebase exploration — effective but token-heavy with no semantic understanding. Cursor uses cloud-based ~3.5 GB embeddings. **qex** sits in between: BM25 full-text search + optional dense vector embeddings in a single ~19 MB binary.

## What It Does

- **Tree-sitter parsing** — Understands code structure across 10 languages. Extracts functions, classes, methods, structs, traits, interfaces as individual chunks
- **BM25 full-text search** — Field-boosted search via Tantivy with 14-field schema. Function names get 5x boost, paths get 2x, docstrings get 1.5x
- **Dense vector search** (optional) — ONNX-based embedding model with HNSW index for semantic similarity
- **Incremental indexing** — Merkle DAG change detection. Only re-indexes modified files (<100ms for unchanged codebases)
- **MCP protocol** — Stdio JSON-RPC transport. Drop-in tool for Claude Code, Zed, or any MCP client

## Quick Start

```
cargo install qex
```

Add to your Claude Code MCP config (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "qex": {
      "command": "qex",
      "args": []
    }
  }
}
```

Claude Code will now have access to `index_codebase` and `search_code` tools.

## How It Works

```
Source Files → Tree-sitter → Code Chunks → BM25 Index ──→ Search Results
                                        ↘ Embedder ──→ Dense Index ↗ (optional)
                                          (ONNX or OpenAI)
```

1. Walk project files (respects `.gitignore`)
2. Parse each file with tree-sitter into semantic chunks (functions, classes, methods)
3. Enrich chunks with tags, complexity scores, docstrings
4. Index into Tantivy (BM25) and optionally into HNSW (dense vectors)
5. Search queries go through analysis, multi-engine retrieval, and multi-factor re-ranking
