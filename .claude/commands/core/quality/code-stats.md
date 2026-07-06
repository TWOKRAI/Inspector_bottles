---
description: Count files/lines/characters per a TOML config (scripts/code_stats/)
---

Запусти счётчик кодовой статистики:

```bash
python scripts/code_stats/code_stats.py
```

> Скрипт ставится автоматически через `claude-kit-project new` (из `.claude/plugins/lang-python/templates/scripts/code_stats/`). Если в проекте его нет — скопируй из seed или используй `tokei .` напрямую.

Полезные варианты вызова:

- **Конкретная папка:** `python scripts/code_stats/code_stats.py --root src/<package>`
- **JSON для разбора:** `python scripts/code_stats/code_stats.py --format json`
- **Топ-N директорий:** `python scripts/code_stats/code_stats.py --group-by directory --limit 20`
- **Свой конфиг:** `python scripts/code_stats/code_stats.py --config <path>`

Конфиг по умолчанию: [scripts/code_stats/code_stats.toml](../../scripts/code_stats/code_stats.toml) — расширения, исключения (`__pycache__`, `.git`, `.venv` и т.п.), флаги учёта комментариев / docstrings / пустых строк, формат вывода.

Подробности и колонки отчёта: [scripts/code_stats/README.md](../../scripts/code_stats/README.md).

**Когда использовать:**
- «Сколько строк кода в модуле X?»
- «Какая папка больше всего весит по коду?» (`--group-by directory`)
- Снимок размера проекта перед рефакторингом.

**НЕ использовать** для архитектурного анализа связей — для этого `mcp__sentrux__dsm` / `/mcp-sentrux:sentrux-health`.

$ARGUMENTS
