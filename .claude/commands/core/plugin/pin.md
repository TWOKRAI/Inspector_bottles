---
description: Pin plugin <id> to a marketplace source (consume) in enabled.yaml and recompose the configuration — source in the form <plugin>@<marketplace>
allowed-tools: Bash(claude-kit-claude plugin pin*)
---

Записывает плагин как consume-объявление (`source: <plugin>@<marketplace>`): файлы ставит сам Claude Code из marketplace-кэша, а наш lockfile фиксирует пин и composer эмитит `enabledPlugins`. Источник класса git/local отвергается — это Phase 6.5 (β).

Использование: `/core:plugin:pin <id> --source <plugin>@<marketplace> [--version X | --sha Y]`

```bash
claude-kit-claude plugin pin $ARGUMENTS
```
