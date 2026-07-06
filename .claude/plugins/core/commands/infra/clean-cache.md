---
description: Clean Python caches (__pycache__, .pytest_cache, *.pyc, .coverage) — dry-run by default
---

Покажи, какие Python-кэши и артефакты инструментов лежат в проекте:

```bash
python scripts/clean_cache/clean_cache.py
```

**По умолчанию работает в dry-run** — только показывает, что *было бы* удалено. Реальное удаление — флаг `--apply`.

> Скрипт ставится автоматически через `claude-kit-project new` (из `.claude/plugins/lang-python/templates/scripts/clean_cache/`).

Что обычно чистит (паттерны настраиваются): `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.tox/`, `htmlcov/`, `*.egg-info/`, `*.pyc`, `*.pyo`, `*.pyd`, `.coverage`, `coverage.xml`.

Не трогает: `.git`, `.venv`, `venv`, `env`, `node_modules`, `.qex`, `.sentrux`.

Полезные варианты (если установлен `scripts/clean_cache/`):
- `--apply` — реальное удаление.
- `--root src/<package>` — только подкаталог.
- `--format json` — machine-readable отчёт для агентов.
- `--apply --quiet` — для CI (exit 0/1/2, без вывода).
- `--min-size 1000000 --limit 20` — только тяжёлые цели, топ-20.

**Exit-коды (если scripts/clean_cache/ установлен):**
- `0` — успех (включая «удалять нечего»).
- `1` — при `--apply` отдельные пути не удалились.
- `2` — отказ slow-rails (root = `/` или `$HOME`), некорректный TOML, нет такого `--root`. Ничего не удалялось.

**Когда использовать:**
- Перед коммитом / билдом артефакта — гарантировать чистый workspace.
- После рефакторинга, переименовавшего/удалившего модули — `*.pyc` от старых имён мешают импортам.
- Освободить место — на репо с длинной историей тестов набегает легко 10–50 МБ.

$ARGUMENTS
