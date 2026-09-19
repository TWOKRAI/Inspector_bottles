---
description: Historical project quality dynamics (metric trends)
---

Show how the project's quality changed over time:

1. Call `mcp__sentrux__evolution` with `path` = the absolute path to the project root.

Show the user:
- A graph/table of `quality_signal` across points in time.
- The trend of each of the 5 metrics (modularity, acyclicity, depth, equality, redundancy) — rising, falling, stable.
- Inflection points — where quality changed sharply (likely a major refactor or a regression).

Use for a retrospective: "Okay, after the T1.1 migration modularity grew by 800 points, acyclicity wasn't hurt — the refactor succeeded."

$ARGUMENTS
