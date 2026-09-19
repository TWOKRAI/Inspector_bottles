---
description: Remove plugin <id> — physically delete its files, drop it from enabled.yaml and recompose the configuration (with auto-backup and rollback on failure)
allowed-tools: Bash(claude-kit-claude plugin remove*)
---

Physically removes the plugin: deletes its folder under `plugins/<id>/`, drops the entry from enabled.yaml, and rebuilds the artifacts. A backup of `.claude/` is created before removal; on failure the engine rolls back. `core` cannot be removed. Requests confirmation (for CI add `--yes`).

Usage: `/core:plugin:remove <id> [--yes]`

```bash
claude-kit-claude plugin remove $ARGUMENTS
```
