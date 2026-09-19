---
description: Pin plugin <id> to a marketplace source (consume) in enabled.yaml and recompose the configuration — source in the form <plugin>@<marketplace>
allowed-tools: Bash(claude-kit-claude plugin pin*)
---

Records the plugin as a consume declaration (`source: <plugin>@<marketplace>`): Claude Code itself installs the files from the marketplace cache, while our lockfile records the pin and the composer emits `enabledPlugins`. A git/local-class source is rejected — that's Phase 6.5 (β).

Usage: `/core:plugin:pin <id> --source <plugin>@<marketplace> [--version X | --sha Y]`

```bash
claude-kit-claude plugin pin $ARGUMENTS
```
