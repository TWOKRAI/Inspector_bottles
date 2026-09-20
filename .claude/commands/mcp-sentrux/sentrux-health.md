---
description: Snapshot of project architectural health (scan + health), metrics and bottleneck
---

Run the sentrux project health check:

1. Call `mcp__sentrux__scan` with `path` = the absolute path to the project root.
2. Call `mcp__sentrux__health` (no parameters — uses the last scan).

Show the user:
- **Quality signal** (0–10000) and its interpretation: <3000 poor, 3000–6000 average, 6000–8000 good, >8000 excellent.
- **Bottleneck** — the root cause of the drop.
- A table of the 5 metrics: modularity, acyclicity, depth, equality, redundancy (raw + score).
- `cross_module_edges` / `total_import_edges`.

If bottleneck = `acyclicity` (there are cycles) — recommend `/mcp-sentrux:sentrux-dsm` to break down the couplings.
If bottleneck = `modularity` — recommend reviewing module boundaries.

$ARGUMENTS
