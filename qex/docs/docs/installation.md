# Installation

## From Source

```
git clone https://github.com/us/qex
cd qex
cargo build --release
```

Binary will be at `target/release/qex` (~19 MB).

### With Dense Vector Search (ONNX)

```
cargo build --release --features dense
```

Binary will be ~36 MB. Requires downloading the embedding model:

```
./scripts/download-model.sh
```

Or via MCP tool:

```json
{"tool": "download_model", "arguments": {"force": false}}
```

The model (Arctic Embed S, 33 MB INT8 quantized) is stored at `~/.qex/models/arctic-embed-s/`.

### With OpenAI Embeddings

```
cargo build --release --features "dense,openai"
```

Set environment variables to use OpenAI:

```bash
export QEX_EMBEDDING_PROVIDER=openai
export QEX_OPENAI_API_KEY=sk-...  # or set OPENAI_API_KEY
```

Works with any OpenAI-compatible API (Ollama, Azure, LiteLLM) by setting `QEX_OPENAI_BASE_URL`.

## Feature Flags

| Flag | Default | Description |
|------|---------|-------------|
| `dense` | off | Enables ONNX embedding + HNSW vector index. Adds `ort`, `ndarray`, `usearch`, `tokenizers` |
| `openai` | off | Enables OpenAI API embedding backend. Adds `ureq` |
| `dense,openai` | off | Both backends available, selected at runtime via `QEX_EMBEDDING_PROVIDER` |

**BM25-only mode** (default) is recommended for most use cases. Dense search adds ~50ms latency per query (ONNX) or ~200ms (OpenAI API) and requires either a model download or API key.

## Claude Code Setup

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "qex": {
      "command": "/path/to/qex",
      "args": []
    }
  }
}
```

Or if installed via `cargo install`:

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

For verbose debug logging:

```json
{
  "mcpServers": {
    "qex": {
      "command": "qex",
      "args": ["--verbose"]
    }
  }
}
```

## Requirements

- Rust 1.75+ (for building from source)
- Docker is **not** required
- No external services — everything runs locally
