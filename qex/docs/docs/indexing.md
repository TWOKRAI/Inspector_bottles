# Indexing

## Indexing Modes

The incremental indexer supports three modes, automatically selected based on state:

| Mode | Condition | Behavior | Speed |
|------|-----------|----------|-------|
| Full | No snapshot exists, or `force: true` | Walk all files, chunk all, index everything | ~20s (dense), ~2s (BM25) |
| Incremental | Snapshot exists, changes detected | Re-index only added/modified files, remove deleted | Proportional to changes |
| Skip | Snapshot valid, no changes | Return immediately | <100ms |

## Pipeline

```
File Walker → Language Detection → Tree-sitter Parse → Chunk Extraction → Enrichment → Index
```

### 1. File Walking

Uses the `ignore` crate for `.gitignore`-compatible traversal. Default ignore list includes 50+ patterns:

- VCS: `.git`, `.svn`, `.hg`
- Dependencies: `node_modules`, `vendor`, `third_party`, `.venv`, `__pycache__`
- Build outputs: `target`, `build`, `dist`, `out`, `.next`
- Binary files: images, fonts, archives, compiled objects
- IDE: `.idea`, `.vscode`, `.vs`
- OS: `.DS_Store`, `Thumbs.db`

### 2. Language Detection

File extensions are mapped to tree-sitter grammars. Files with unrecognized extensions are skipped.

### 3. Tree-sitter Parsing

Each file is parsed into an AST using the appropriate tree-sitter grammar. The AST is then walked to extract code chunks. Parsing is parallelized across files via `rayon`.

### 4. Chunk Extraction

Language-specific chunkers walk the AST and extract semantic units:

- **Functions/Methods** — Including parameters, return types, body
- **Classes/Structs** — Including fields, methods, inheritance
- **Interfaces/Traits** — Including method signatures
- **Enums** — Including variants
- **Impl blocks** (Rust) — Including associated functions
- **Macros** (Rust) — Including body
- **Markdown sections** — Split by headings

### 5. Enrichment

Each chunk is enriched with metadata:

**Tags** — Semantic tags inferred from content:
- `async` — Contains async/await patterns
- `auth` — Authentication-related code
- `database` — Database operations
- `error_handling` — Error/exception handling
- `test` — Test code
- `api` — HTTP/API handlers
- `io` — File/network I/O
- And more

**Complexity** — A heuristic score based on nesting depth, branching, and size.

**Docstrings** — Extracted from preceding comments or doc attributes.

**Decorators** — Python decorators, Rust `#[...]` attributes, TypeScript decorators.

## Merkle DAG Change Detection

Fast change detection using a SHA-256 hash tree.

### How It Works

1. Every file is hashed (SHA-256) to create a leaf node
2. Directory hashes are computed from sorted child hashes
3. The root hash represents the entire project state
4. On re-index, the new root hash is compared to the stored snapshot
5. If roots match → skip (no changes). If different → walk the tree to find changed files

### Snapshot Lifecycle

```
First index → Build Merkle DAG → Save snapshot to disk
Re-index    → Build new DAG → Compare roots → Diff → Incremental update → Save new snapshot
```

Snapshots are stored at `~/.qex/projects/{name}_{hash}/snapshot.json` with a metadata file tracking the last check time. Snapshots older than 5 minutes trigger a re-check.

## Storage Layout

```
~/.qex/
├── projects/
│   └── {project_name}_{hash8}/
│       ├── project_info.json           # Project metadata
│       ├── tantivy/                    # BM25 index files
│       ├── dense/                      # Vector index (optional)
│       │   ├── dense.usearch           # HNSW index
│       │   ├── dense_mapping.json      # Chunk ID ↔ vector key mapping (atomic write)
│       │   └── dense_meta.json         # Embedder metadata (provider, model, dimensions)
│       ├── snapshot.json               # Merkle DAG
│       ├── snapshot_metadata.json      # Last check timestamp
│       └── stats.json                  # Indexing statistics
│
└── models/
    └── arctic-embed-s/                 # Embedding model (optional)
        ├── model.onnx                  # 33 MB, INT8 quantized
        ├── tokenizer.json
        └── config.json
```

Project directories are named with a truncated hash to avoid collisions when multiple projects share the same name.
