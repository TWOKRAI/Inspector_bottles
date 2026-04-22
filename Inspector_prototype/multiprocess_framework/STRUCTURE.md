# Структура `multiprocess_framework`

Документ отражает **фактическое** дерево пакета (нижний регистр, `snake_case`). Тесты лежат в **`modules/<name>/tests/`**, а не в отдельном корне `multiprocess_framework/tests/`. Отдельной папки **`examples/`** в пакете нет — примеры смотрите в `multiprocess_prototype/` и в `docs/QUICK_START.md`.

## Дерево каталогов

```
multiprocess_framework/
├── __init__.py                 # Публичный фасад (tiered re-exports)
├── README.md
├── DECISIONS.md                # Глобальные ADR (ADR-NNN)
├── ARCHITECTURE.md
├── STRUCTURE.md                # Этот файл
├── MODULES_STATUS.md
├── DOCUMENTATION_INDEX.md
├── PROBLEMS.md
├── modules/
│   ├── __init__.py
│   ├── conftest.py             # Общие фикстуры pytest для модулей
│   ├── pytest.ini
│   ├── base_manager/
│   ├── channel_routing_module/
│   ├── command_module/
│   ├── config_module/
│   ├── console_module/         # опционально; вне scope production core
│   ├── data_schema_module/
│   ├── dispatch_module/
│   ├── error_module/
│   ├── frontend_module/
│   ├── logger_module/
│   ├── message_module/
│   ├── process_manager_module/
│   ├── process_module/
│   ├── registers_module/
│   ├── router_module/
│   ├── shared_resources_module/
│   ├── sql_module/
│   ├── statistics_module/
│   └── worker_module/
└── docs/
    ├── README.md
    ├── FRAMEWORK_OVERVIEW.md
    ├── ARCHITECTURE_REFERENCE.md
    ├── ARCHITECTURE_MODULE_CATALOG.md
    ├── ROUTING_GLOSSARY.md
    ├── DIAGRAMS.md             # Сводные mermaid-диаграммы
    ├── QUICK_START.md
    ├── EXTENSION_GUIDE.md
    ├── CONFIG_GUIDE.md
    ├── TROUBLESHOOTING.md
    ├── ADR_REGISTRY.md
    ├── MODULE_README_TEMPLATE.md
    ├── FRONTEND_COMMAND_LAUNCHER_ROADMAP.md
    └── archive/                # Устаревшие / объединённые документы
```

**Всего пакетов под `modules/`:** 19 (включая `console_module`, `sql_module`, `frontend_module`). В обзорах «ядро» иногда считают без опциональных UI/SQL/консоли — см. [docs/ARCHITECTURE_MODULE_CATALOG.md](./docs/ARCHITECTURE_MODULE_CATALOG.md).

## Принципы

1. **Один модуль — одна папка** в `modules/` с `interfaces.py`, `README.md`, `STATUS.md`, `tests/`.
2. **Импорты между модулями** — через публичный API чужого модуля (обычно `interfaces.py`), без `sys.path` hacks.
3. **Граница процессов** — только `dict` (Dict at Boundary); Pydantic — внутри процесса.

## Импорты (пользователи фреймворка)

```python
from multiprocess_framework import SystemLauncher, ProcessModule, SchemaBase, process
# или явно:
from multiprocess_framework.modules.process_manager_module import SystemLauncher
```

## Импорты внутри фреймворка

Между модулями — **абсолютные** импорты из `multiprocess_framework.modules.<name>`. Внутри модуля — относительные (`from ..interfaces import ...`).

## Добавление нового модуля

1. Создать `modules/new_module/` с `__init__.py`, `interfaces.py`, `README.md`, `STATUS.md`, `tests/`.
2. При необходимости добавить реэкспорт в `multiprocess_framework/__init__.py`.
3. Обновить `MODULES_STATUS.md`, `docs/ARCHITECTURE_MODULE_CATALOG.md`, при архитектурных решениях — `DECISIONS.md` или `modules/new_module/DECISIONS.md` в формате **ADR-{CODE}-NNN** (см. `docs/ADR_REGISTRY.md`).
