---
description: Remove plugin <id> — physically delete its files, drop it from enabled.yaml and recompose the configuration (with auto-backup and rollback on failure)
allowed-tools: Bash(claude-kit-claude plugin remove*)
---

Физически удаляет плагин: стирает его папку под `plugins/<id>/`, убирает запись из enabled.yaml и пересобирает артефакты. Перед удалением создаётся бэкап `.claude/`; при сбое движок откатывает. `core` удалить нельзя. Запрашивает подтверждение (для CI добавь `--yes`).

Использование: `/core:plugin:remove <id> [--yes]`

```bash
claude-kit-claude plugin remove $ARGUMENTS
```
