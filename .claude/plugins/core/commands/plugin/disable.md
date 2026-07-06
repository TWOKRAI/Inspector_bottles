---
description: Disable plugin <id> — remove it from enabled.yaml and recompose the configuration (the plugin's files stay on disk)
allowed-tools: Bash(claude-kit-claude plugin disable*)
---

Отключает плагин и пересобирает артефакты конфигурации. Файлы плагина на диске не удаляются.

Использование: `/core:plugin:disable <id>`

```bash
claude-kit-claude plugin disable $ARGUMENTS
```
