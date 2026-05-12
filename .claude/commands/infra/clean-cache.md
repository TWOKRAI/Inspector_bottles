---
description: Чистка Python-кэшей (__pycache__, .pytest_cache, *.pyc, .coverage) — dry-run по умолчанию
---

Покажи, какие Python-кэши и артефакты инструментов лежат в проекте:

```bash
python scripts/clean_cache/clean_cache.py
```

**По умолчанию работает в dry-run** — только показывает, что *было бы* удалено. Реальное удаление — флаг `--apply`.

Что чистит (паттерны настраиваются): `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.tox/`, `htmlcov/`, `*.egg-info/`, `*.pyc`, `*.pyo`, `*.pyd`, `.coverage`, `coverage.xml`.

Не трогает: `.git`, `.venv`, `venv`, `env`, `node_modules`, `.qex`, `.sentrux`, `multiprocess_prototype_backup` (snapshot owner).

Конфиг: [scripts/clean_cache/clean_cache.toml](../../scripts/clean_cache/clean_cache.toml). Детали в [README.md](../../scripts/clean_cache/README.md).

Полезные варианты:
- `python scripts/clean_cache/clean_cache.py --apply` — **реальное удаление** найденного.
- `python scripts/clean_cache/clean_cache.py --root multiprocess_framework` — только подкаталог.
- `python scripts/clean_cache/clean_cache.py --format json` — machine-readable отчёт для агентов.
- `python scripts/clean_cache/clean_cache.py --apply --quiet` — для CI (exit 0/1/2, без вывода).
- `python scripts/clean_cache/clean_cache.py --min-size 1000000 --limit 20` — только тяжёлые цели, топ-20.

**Exit-коды:**
- `0` — успех (включая «удалять нечего»).
- `1` — при `--apply` отдельные пути не удалились (см. `errors[]` в JSON).
- `2` — отказ slow-rails (root = `/` или `$HOME`), некорректный TOML, нет такого `--root`. Ничего не удалялось.

**Когда использовать:**
- Перед коммитом / билдом артефакта — гарантировать чистый workspace.
- После рефакторинга, переименовавшего/удалившего модули — `*.pyc` от старых имён мешают импортам.
- Регулярная гигиена (через `/loop`, `/schedule` или просто руками).
- Освободить место — на репо с длинной историей тестов набегает легко 10–50 МБ.

**Замечания:**
- Slow-rails: скрипт **откажется** работать с корнем `/` или `$HOME` — это намеренно. Отключить можно `--no-safety`, но это редко нужно.
- Глобы матчат **имя**, не путь (`*.egg-info` — каталог с любым именем `*.egg-info`, не путь). Для path-фильтров — `[exclude].path_patterns` в конфиге.
- На больших репо `_dir_stats` (рекурсивный размер каждого кэша) — основное время. Используй `--quiet`, если важна только сводка.

$ARGUMENTS
