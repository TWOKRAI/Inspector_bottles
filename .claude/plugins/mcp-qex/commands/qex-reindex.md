---
description: Incremental qex index update (Merkle-diff, seconds-minutes). For a full reindex — /mcp-qex:qex-rebuild
---

Incremental indexing: qex compares the Merkle snapshot from `~/.qex/projects/<hash>/snapshot.json`
against the current state of the files and reindexes only what changed. On a large repo this is seconds-minutes instead of dozens of minutes.

Before indexing, make sure Ollama is running:

```bash
curl -s --max-time 1 http://localhost:11434/ | grep -q running && echo UP || echo DOWN
```

If DOWN — suggest the user run `/core:infra:cold-start`, do not index.

If UP — call the tool `mcp__qex__index_codebase` with parameters:
- `path`: absolute path to the project root
- **WITHOUT** the `force` parameter (or `force: false`)

When it finishes, show the summary: file count, chunks, time.

If nothing changed in the repo since the last indexing — qex returns the result in seconds without doing work.

If the incremental run **fails on a batch timeout** (8–10s of embedding against qex's ~10s limit) —
don't retry the call by hand: `uv run --no-project python .claude/plugins/mcp-qex/reindex_retry.py` drives `index_codebase`
in a loop up to 12 attempts, progress carries over between attempts, and each attempt's qex stderr goes to
`.claude/.qex/logs/reindex_retry/`.

If you need **model warm-up and live progress** (qex itself doesn't report progress, and
`get_indexing_status` only shows the last committed index) —
`uv run --no-project python .claude/plugins/mcp-qex/reindex_progress.py`: warms the embedding model with a long
`keep_alive` (removes the cold-load timeout on the first chunk), re-warms periodically and prints
an embedded-chunks counter with the rate. Percentage and ETA — only with an explicit `--total`.

When a **full** reindex is needed (not an incremental one) — the user should call `/mcp-qex:qex-rebuild`:
- the embedding model was changed;
- the snapshot is corrupted / the index returns garbage;
- a massive refactor (>50% of files).

$ARGUMENTS
