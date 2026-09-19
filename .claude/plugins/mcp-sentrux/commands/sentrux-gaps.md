---
description: Test gaps — modules and areas without test coverage
---

Run the analysis of modules not covered by tests:

1. Make sure there was a fresh scan (if not — call `mcp__sentrux__scan` with `path` to the project root).
2. Call `mcp__sentrux__test_gaps` with `path` = the absolute path to the project root.

Show the user:
- List of modules **without tests** (priority: those with a high `cross_module_edges` value — many external dependencies).
- Modules **with low coverage** relative to their size/coupling.
- Recommended order: what to cover first, and why.

Use before `/dev:ship` so you don't commit a regression into an uncovered piece.

$ARGUMENTS
