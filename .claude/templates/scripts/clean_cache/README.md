# clean_cache

Чистка Python-кэшей и артефактов инструментов: `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.pyc`, `.coverage`, `htmlcov/`, `*.egg-info/`. Stdlib-only, Python 3.12+.

**Безопасно по умолчанию:** dry-run; реальное удаление — флаг `--apply`.

## Быстрый старт

```bash
# Что было бы удалено (dry-run) с дефолтным конфигом — сканирует "."
python scripts/clean_cache/clean_cache.py

# РЕАЛЬНОЕ удаление
python scripts/clean_cache/clean_cache.py --apply

# Подсмотреть в подкаталог
python scripts/clean_cache/clean_cache.py --root src

# JSON для агентов (machine-readable отчёт + список целей)
python scripts/clean_cache/clean_cache.py --format json

# Для CI — тихий режим, exit-код 0 (ok) / 1 (ошибки удаления) / 2 (отказ)
python scripts/clean_cache/clean_cache.py --apply --quiet
```

## Что настраивается в `clean_cache.toml`

| Секция | Параметр | Назначение |
|--------|----------|------------|
| `[scan]` | `root`, `follow_symlinks` | Откуда сканировать |
| `[delete]` | `dirs`, `files` | Что считать кандидатом на удаление (fnmatch-глобы по имени) |
| `[exclude]` | `dirs`, `path_patterns` | Куда вообще не заходить (`.git`, `.venv`, `data` и т.п.) |
| `[output]` | `format`, `sort_by`, `sort_order`, `limit`, `min_size` | Как показать отчёт |
| `[safety]` | `forbid_dangerous_roots`, `timeout_sec` | Slow-rails |

CLI-флаги (`--root`, `--format`, `--sort-by`, `--limit`, `--min-size`) перекрывают значения конфига.

## Дефолтные паттерны

**Удаляемые директории:** `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, `htmlcov`, `*.egg-info`.
**Удаляемые файлы:** `*.pyc`, `*.pyo`, `*.pyd`, `.coverage`, `.coverage.*`, `coverage.xml`.

**Исключения (не сканируются):** `.git`, `.venv`, `venv`, `env`, `node_modules`, `.qex`, `.sentrux`, `data` (последнее — по правилу проекта, см. [`CLAUDE.md`](../../CLAUDE.md)).

Чтобы добавить свой паттерн — отредактируй `clean_cache.toml` или подключи свой конфиг через `--config path/to/other.toml`.

## Колонки отчёта (`--format table`)

Две части:

1. **Сводка по паттернам:**
   - `pattern` — какое правило сматчилось (`__pycache__`, `*.pyc`, …)
   - `count` — сколько целей удалить (для `__pycache__` — это число каталогов)
   - `files` — суммарное число обычных файлов внутри (для каталога — рекурсивно)
   - `size` — суммарный размер, human-readable

2. **Топ-цели:** `[D|F]  size  rel/path` — пометка `D` для каталога, `F` для файла.

В режиме `--apply` дополнительно показывается секция `ERRORS:` с путями, которые не удалось удалить (и почему).

## Выходные exit-коды

| Код | Когда |
|-----|-------|
| `0` | Успех. Включая «удалять нечего». |
| `1` | Сканирование прошло, но при `--apply` отдельные пути не удалились (см. отчёт / `errors[]` в JSON). |
| `2` | Не удалось начать: некорректный TOML, нет такого `--root`, отказ slow-rails. **Ничего не удалялось.** |

## Safety / slow-rails

- **`forbid_dangerous_roots`** (по умолчанию `true`): отказ работать с корнем, который равен `/`, `$HOME` или disk anchor. Отключается флагом `--no-safety` для редких задач (например, чистка `~/.cache/something`).
- **`[exclude].dirs`** работает на уровне сканирования: внутрь исключённого каталога os.walk не заходит вообще, даже если внутри есть валидные цели для удаления.
- **dry-run по умолчанию.** Никакой опции «удалить без явного `--apply`» нет.

## JSON-вывод (для агентов)

```json
{
  "mode": "dry-run",
  "summary": { "count": 12, "total_size": 3145728, "total_files": 87 },
  "targets": [
    { "path": "scripts/__pycache__", "kind": "dir",
      "pattern": "__pycache__", "size": 2097152, "files": 3 },
    { "path": "x/y.pyc", "kind": "file",
      "pattern": "*.pyc", "size": 4096, "files": 1 }
  ]
}
```

В режиме `--apply` добавляются поля:
- `removed_count` — сколько целей реально удалено;
- `errors[]` — массив объектов `{path, message}` для не удалённых.

Это даёт агенту контракт: парсить `summary.total_size`, чекать `errors == []`, читать `targets[].path` для аудита.

## Когда полезно

- Перед коммитом — убрать `__pycache__/` из staging (хотя `.gitignore` уже их прячет, размер репо растёт).
- После рефакторинга, который переименовал/удалил модули — `*.pyc` от старых имён теряют связь с исходниками и мешают импортам.
- В CI перед билдом артефакта — гарантировать «чистый» каталог.
- Регулярная гигиена (через cron / `/loop` / `/schedule`).

## Ограничения

- Глобы — по **именам**, не по полному пути (кроме `[exclude].path_patterns`, который сравнивает относительный путь).
- `*.egg-info` намеренно матчит каталог: внутри `setup.py`-проектов это сборочный артефакт; не использовать в каталоге, где `*.egg-info` — продакшен-артефакт.
- Скрипт **не трогает** содержимое исключённых каталогов, даже если внутри есть валидные кандидаты.
- На больших репо `_dir_stats` (рекурсивный обход каждого `__pycache__`) — основное время. Если каталогов много — рассмотри `--quiet` + JSON.
