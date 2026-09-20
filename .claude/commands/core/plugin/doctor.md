---
description: Check plugin configuration integrity — report missing/broken/available plugins without changing files
allowed-tools: Bash(claude-kit-claude plugin doctor*)
---

Read-only diagnostics: shows plugins from enabled.yaml without a folder on disk (missing), broken manifests (broken), plugins on disk outside enabled.yaml (available). Changes nothing.

```bash
claude-kit-claude plugin doctor $ARGUMENTS
```
