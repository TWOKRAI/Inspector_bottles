---
description: Full qex reindex from scratch (force=true, 30-60 min on a large repo). Use only when changing the embedding model or when the index is corrupted
---

Full reindex — **slow** (dozens of minutes on a large repo). By default use `/mcp-qex:qex-reindex` (incremental).

Before reindexing, ask the user for confirmation — this is an expensive operation. If they agree:

1. Check Ollama:

```bash
curl -s --max-time 1 http://localhost:11434/ | grep -q running && echo UP || echo DOWN
```

If DOWN — run `/core:infra:cold-start`, do not index.

2. Call the tool `mcp__qex__index_codebase`:
   - `path`: absolute path to the project root
   - `force`: **true**

When it finishes, show the summary: file count, chunks, time.

$ARGUMENTS
