---
description: Dependency Structure Matrix — module relationships and cycles
---

Run the DSM analysis:

1. Make sure there was a fresh scan (if not — call `mcp__sentrux__scan` with `path` to the project root).
2. Call `mcp__sentrux__dsm` with `path` = the absolute path to the project root.

Show the user:
- List of cycles (if any) — which modules closed the loop.
- Top-N heavily coupled modules (high coupling).
- Candidates for breaking couplings: where to insert an interface / DI / event.

Take the project context into account: architecture rules (if `.sentrux/rules.toml` exists) define the allowed layers and boundaries. If there is a `_stack.md` "Layers" section — cross-check the found violations against it.

$ARGUMENTS
