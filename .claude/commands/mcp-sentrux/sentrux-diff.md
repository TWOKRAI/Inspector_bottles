---
description: Compare current state against the recorded baseline (session_end)
---

Compare the current quality against the baseline saved via `/mcp-sentrux:sentrux-baseline`:

1. Call `mcp__sentrux__rescan` with `path` = the absolute path to the project root (or `mcp__sentrux__scan` if rescan is unavailable).
2. Call `mcp__sentrux__session_end` (no parameters).

Show the user:
- `signal_before` → `signal_after` (with delta and direction: ✅ improved / ⚠️ unchanged / ❌ degraded).
- Which metric moved the most, and in which direction.
- A short summary: safe to commit, or should part of the changes be rolled back.

If pass=false (degradation) — recommend `/mcp-sentrux:sentrux-dsm` to find where new couplings/cycles appeared.

$ARGUMENTS
