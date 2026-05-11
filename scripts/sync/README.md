# sync — авто-синхронизация генерируемых разделов ADR-документации

Каркас, который пересобирает таблицы и оглавление между маркерными комментариями в `multiprocess_framework/DECISIONS.md` и `docs/ADR_REGISTRY.md`. Источник истины — заголовки `## ADR-…` в локальных `modules/*/DECISIONS.md` и в самом глобальном `DECISIONS.md`.

Запускать из корня проекта: `python -m scripts.sync …`.

## Запуск

```bash
python -m scripts.sync              # write-режим: обновить файлы между маркерами
python -m scripts.sync --check      # CI: вывести unified diff и упасть (exit 1) при дрифте
python -m scripts.sync --list       # перечислить зарегистрированные sync-модули
python -m scripts.sync --only adr_toc   # применить ровно один модуль
```

Обязательно, когда:
- правишь `multiprocess_framework/DECISIONS.md`;
- правишь `multiprocess_framework/modules/*/DECISIONS.md`;
- добавляешь новый модуль с локальным ADR (см. ниже).

`/validate` ловит дрифт в CI — если sync не запущен, `python scripts/validate.py` упадёт.

## Архитектура

```
scripts/sync/
├── __main__.py        # CLI: парсинг флагов, регистрация модулей, вызов apply_sync
├── registry.py        # SyncModule (Protocol), replace_between_markers, apply_sync
├── _adr_layers.py     # ручной реестр (имя_модуля, слой) — единственное "ручное" место
├── adr_modules.py     # таблица «Модульные решения» + «Коды модулей»
├── adr_toc.py         # «Оглавление (по номеру)» для глобальных ADR
├── adr_obsolete.py    # раздел «Устарело» (только ссылки)
└── tests/             # unit-тесты на каждый модуль и на CLI
```

### Контракт sync-модуля

Каждый модуль реализует `Protocol` `SyncModule` из `registry.py`:

- `name: str` — уникальный идентификатор (`adr_modules`, `adr_toc`, `adr_obsolete`).
- `targets: list[tuple[Path, str]]` — пары `(файл, marker_key)`. На один файл может приходиться несколько маркеров.
- `render(marker_key) -> str` — текст, который вставляется между `<!-- {marker_key}:BEGIN -->` и `<!-- {marker_key}:END -->`.

`apply_sync` находит маркеры, заменяет содержимое и (в `--check`) показывает unified diff.

### Маркеры в документации

| Маркер | Файл | Что генерируется |
|--------|------|------------------|
| `<!-- ADR-INDEX:BEGIN/END -->` | `multiprocess_framework/DECISIONS.md` | Таблица «Модульные решения» |
| `<!-- ADR-CODES:BEGIN/END -->` | `multiprocess_framework/docs/ADR_REGISTRY.md` | Таблица «Коды модулей» |
| `<!-- ADR-TOC:BEGIN/END -->` | `multiprocess_framework/DECISIONS.md` | «Оглавление (по номеру)» |
| `<!-- ADR-OBSOLETE:BEGIN/END -->` | `multiprocess_framework/DECISIONS.md` | «Устарело» (ссылки на ADR) |

Если маркера нет — `MarkerNotFound`, sync падает: маркер либо добавляется руками в документ, либо sync-модуль выпиливается.

## Что генерируется из чего

| Sync-модуль | Источник | Цель |
|-------------|----------|------|
| `adr_modules` | Заголовки `## ADR-{CODE}-NNN: …` в `modules/*/DECISIONS.md` + порядок из `_adr_layers.MODULE_LAYERS` | Две таблицы (по `ADR-INDEX` и `ADR-CODES`) |
| `adr_toc` | Числовые заголовки `## ADR-NNN: …` в `multiprocess_framework/DECISIONS.md` | Оглавление |
| `adr_obsolete` | Те же ADR, но со статусом `is_obsolete=True` | Список «Устарело» |

`adr_obsolete` переиспользует парсер `scan_global_adrs` из `adr_toc.py`.

## Добавить новый модуль с локальным ADR

1. Создай `multiprocess_framework/modules/<X>/DECISIONS.md` с заголовками `## ADR-{CODE}-NNN: …`.
2. Добавь строку в `MODULE_LAYERS` в [`_adr_layers.py`](_adr_layers.py): `("<X>", "<Слой>")`.
3. Запусти `python -m scripts.sync` — обе таблицы обновятся.
4. Проверь `/validate` — дрифта быть не должно.

Если у модуля локальных ADR нет, но он отмечен в DECISIONS.md как «без локальных ADR» — добавь его в `MODULES_WITHOUT_LOCAL_ADR` (см. конец `_adr_layers.py`).

## Зарегистрировать новый sync-модуль

1. Создай `scripts/sync/<имя>.py`, реализуй `SyncModule` (см. `registry.py`).
2. Добавь маркер `<!-- <ИМЯ>:BEGIN/END -->` в целевой документ.
3. Импортируй в `__main__.py` и добавь в `SYNC_MODULES`.
4. Покрой тестами в `tests/test_<имя>.py` (smoke + render).

## Тесты

```bash
pytest scripts/sync/tests/ -v
```

Проверяют:
- `test_registry.py` — `replace_between_markers`, `apply_sync` (write/check режимы).
- `test_adr_modules.py`, `test_adr_toc.py`, `test_adr_obsolete.py` — парсинг и рендер каждого модуля.
- `test_cli.py` — `--list`, `--only`, `--check`, exit-коды.

## Ограничения

- Сортировка и группировка модулей — **по `_adr_layers.MODULE_LAYERS`**, не по алфавиту. Это сознательно: порядок отражает архитектурные слои (Foundation → Process → Application).
- Парсер заголовков — регэксп по `^## ADR-…`, ничего более сложного (без markdown-AST). Если меняешь стиль заголовков ADR — обнови регэкспы в `adr_modules.py` / `adr_toc.py`.
- Sync не трогает текст вне маркеров. Тело ADR редактируется руками.
