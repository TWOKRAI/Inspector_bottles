---
description: Recompose the project configuration from the current enabled.yaml — update .mcp.json and settings.json
allowed-tools: Bash(claude-kit-claude plugin sync*)
---

Rebuilds the configuration artifacts (.mcp.json, settings.json) from the current state of enabled.yaml. Use after manual edits to enabled.yaml.

```bash
claude-kit-claude plugin sync $ARGUMENTS
```
