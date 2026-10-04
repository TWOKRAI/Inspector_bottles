---
description: Run the sentrux check CLI against .sentrux/rules.toml (exit 0/1). Call for the layer-boundary verdict; the MCP check_rules covers only part of the rules.
---

Run the `sentrux check` CLI validator — it fits CI and pre-commit, exits with code 0 (all clear) or 1 (violations found).

Determine the absolute path to the project root and run:

```bash
sentrux check "$(git rev-parse --show-toplevel)"
```

Show the user:
- The final exit code and `Quality: NNNN`.
- The list of failed rules (if any) with the offending files.
- A recommendation: run `/mcp-sentrux:sentrux-rules` for an interactive breakdown, or fix it directly.

If `.sentrux/rules.toml` is missing — say so and show the minimal template (see `/mcp-sentrux:sentrux-rules`).

$ARGUMENTS
