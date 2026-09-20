---
description: Disable plugin <id> — remove it from enabled.yaml and recompose the configuration (the plugin's files stay on disk)
allowed-tools: Bash(claude-kit-claude plugin disable*)
---

Disables the plugin and rebuilds the configuration artifacts. The plugin's files on disk are not removed.

Usage: `/core:plugin:disable <id>`

```bash
claude-kit-claude plugin disable $ARGUMENTS
```
