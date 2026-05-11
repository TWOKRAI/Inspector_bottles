---
description: Подсчёт файлов/строк/символов по TOML-конфигу (scripts/code_stats/)
---

Запусти счётчик кодовой статистики:

```bash
python scripts/code_stats/code_stats.py
```

Полезные варианты вызова:

- **Конкретная папка:** `python scripts/code_stats/code_stats.py --root multiprocess_framework`
- **JSON для разбора:** `python scripts/code_stats/code_stats.py --format json`
- **Топ-N директорий:** `python scripts/code_stats/code_stats.py --group-by directory --limit 20`
- **Свой конфиг:** `python scripts/code_stats/code_stats.py --config <path>`

Конфиг по умолчанию: [scripts/code_stats/code_stats.toml](../../scripts/code_stats/code_stats.toml) — расширения, исключения (`__pycache__`, `.git`, `.venv`, `multiprocess_prototype_backup` и т.п.), флаги учёта комментариев / docstrings / пустых строк, формат вывода.

Подробности и колонки отчёта: [scripts/code_stats/README.md](../../scripts/code_stats/README.md).

**Когда использовать:**
- «Сколько строк кода в модуле X?»
- «Какая папка больше всего весит по коду?» (`--group-by directory`)
- Снимок размера фреймворка / прототипа / Services перед рефакторингом.

**НЕ использовать** для архитектурного анализа связей — для этого `mcp__sentrux__dsm` / `/sentrux-health`.

$ARGUMENTS
