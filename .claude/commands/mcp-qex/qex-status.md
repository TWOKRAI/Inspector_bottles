---
description: qex index status (file count, chunks, index date, languages)
---

Call the tool `mcp__qex__get_indexing_status` with the parameter `path` = absolute path to the current project root.

Show the result to the user as a table:
- Indexed: ✅/❌
- Files / Chunks
- Languages
- Last indexed (how long ago)
- Dense search available

If `last_indexed` is older than 7 days or there were recent commits — recommend `/mcp-qex:qex-reindex` (incremental update via Merkle-diff, seconds-minutes).
A full reindex (`/mcp-qex:qex-rebuild`) is needed only when the embedding model changes or the index is corrupted.
