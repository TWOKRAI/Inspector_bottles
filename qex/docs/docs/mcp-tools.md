# MCP Tools

qex exposes 5 tools via the Model Context Protocol (JSON-RPC 2.0 over stdio).

## index_codebase

Index a project directory for semantic code search.

```json
{
  "tool": "index_codebase",
  "arguments": {
    "path": "/home/user/my-project",
    "force": false,
    "extensions": [".rs", ".py"]
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | yes | — | Absolute path to project root |
| `force` | bool | no | `false` | Force full re-index (ignores Merkle snapshot) |
| `extensions` | string[] | no | all supported | Only index files with these extensions |

**Behavior:**

- First call: full index (walks all files, chunks, indexes)
- Subsequent calls: incremental (only re-indexes changed files via Merkle DAG)
- With `force: true`: always full re-index

**Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Indexed 423 chunks from 87 files in 2.1s (incremental)"
    }
  ]
}
```

## search_code

Search the indexed codebase.

```json
{
  "tool": "search_code",
  "arguments": {
    "path": "/home/user/my-project",
    "query": "error handling middleware",
    "limit": 10,
    "extension_filter": ".rs"
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | yes | — | Project path (must be indexed) |
| `query` | string | yes | — | Search query (natural language or symbol name) |
| `limit` | int | no | `20` | Maximum results to return |
| `extension_filter` | string | no | all | Only return results from files with this extension |

**Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Found 5 results for 'error handling middleware':\n\n[1] src/api/middleware.rs:45-78 (function: error_handler)\n...\n\n[2] src/api/recovery.rs:12-34 (function: recover_panic)\n..."
    }
  ]
}
```

Each result includes:
- File path and line range
- Chunk type and name
- Full source code of the chunk
- Relevance score

## get_indexing_status

Check the indexing status for a project.

```json
{
  "tool": "get_indexing_status",
  "arguments": {
    "path": "/home/user/my-project"
  }
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Project path |

**Response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Index status for my-project:\n- Chunks: 423\n- Files: 87\n- Last indexed: 2026-03-04T10:30:00Z\n- Index age: 5m ago"
    }
  ]
}
```

## clear_index

Delete all index data for a project.

```json
{
  "tool": "clear_index",
  "arguments": {
    "path": "/home/user/my-project"
  }
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Project path |

Removes the entire project directory under `~/.qex/projects/`, including BM25 index, dense index, Merkle snapshot, and stats.

## download_model

Download the embedding model for dense vector search. Only available when built with the `dense` feature.

```json
{
  "tool": "download_model",
  "arguments": {
    "force": false
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `force` | bool | no | `false` | Re-download even if model exists |

Downloads Snowflake Arctic Embed S (33 MB, INT8 quantized) to `~/.qex/models/arctic-embed-s/`.
