---
description: Record a quality baseline before refactoring (session_start)
---

Record the reference point before starting a refactor/changes:

1. Call `mcp__sentrux__scan` with `path` = the absolute path to the project root (fresh metrics).
2. Call `mcp__sentrux__session_start` (no parameters).

Show the user:
- `quality_signal` baseline (0–10000).
- The current bottleneck.
- A reminder: after the changes, run `/mcp-sentrux:sentrux-diff` to see whether it improved or degraded.

Use before tasks at the level of:
- a major refactor (>5 files or an API change between processes),
- breaking cycles,
- a module migration.

$ARGUMENTS
