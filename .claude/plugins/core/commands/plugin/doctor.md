---
description: Check plugin configuration integrity — report missing/broken/available plugins without changing files
allowed-tools: Bash(claude-kit-claude plugin doctor*)
---

Read-only диагностика: показывает плагины из enabled.yaml без папки на диске (missing), сломанные манифесты (broken), плагины на диске вне enabled.yaml (available). Ничего не изменяет.

```bash
claude-kit-claude plugin doctor $ARGUMENTS
```
