# Структура `multiprocess_framework`

Документ отражает фактическое дерево пакета. Тесты лежат в `modules/<name>/tests/`.

## Дерево каталогов

```
multiprocess_framework/
├── __init__.py                 # Публичный фасад (49 экспортов)
├── README.md
├── SPEC.md                     # Главное ТЗ
├── DOCUMENTATION_INDEX.md
├── MODULES_STATUS.md
├── PROBLEMS.md
├── DECISIONS.md                # Глобальные ADR (ADR-NNN)
├── STRUCTURE.md                # Этот файл
├── modules/
│   ├── __init__.py
│   ├── conftest.py             # Общие фикстуры pytest
│   ├── pytest.ini              # testpaths
│   ├── base_manager/
│   ├── channel_routing_module/
│   ├── command_module/
│   ├── config_module/
│   ├── console_module/
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
├── docs/
│   ├── README.md
│   ├── MODULES_OVERVIEW.md     # Навигатор
│   ├── MODULE_CONTRACTS.md
│   ├── INTERACTION_FLOWS.md
│   ├── DESIGN_RULES.md
│   ├── GLOSSARY.md
│   ├── ROUTING_GLOSSARY.md
│   ├── DIAGRAMS.md
│   ├── QUICK_START.md
│   ├── TROUBLESHOOTING.md
│   ├── EXTENSION_GUIDE.md
│   ├── CONFIG_GUIDE.md
│   ├── ADR_REGISTRY.md
│   ├── MODULE_README_TEMPLATE.md
│   └── archive/                # Устаревшие документы
├── tests/                      # Интеграционные тесты
│   ├── integration/
│   ├── run_all_tests.py
│   └── run_unit_tests.py
└── tools/
    ├── module_validator.py
    └── validate_all_modules.py
```

**Всего пакетов под `modules/`:** 19. Список и краткая роль — [`docs/MODULES_OVERVIEW.md`](docs/MODULES_OVERVIEW.md).

## Принципы организации

1. **Один модуль — одна папка** в `modules/` с обязательными файлами: `__init__.py`, `interfaces.py`, `README.md`, `STATUS.md`, `DECISIONS.md`, `tests/`.
2. **Импорты между модулями** — каноничные: `from multiprocess_framework.modules.<X> import Y`. Никаких top-level импортов и `sys.path`-хаков.
3. **Граница процессов** — только `dict` (Dict at Boundary); Pydantic — внутри процесса.
4. **Публичный API** — только через `interfaces.py` чужого модуля.

## Импорты для пользователей фреймворка

```python
# С корневого фасада (рекомендуется):
from multiprocess_framework import SystemLauncher, ProcessModule, SchemaBase, process

# Подробный путь (тоже корректно):
from multiprocess_framework.modules.process_manager_module import SystemLauncher
```

## Импорты внутри фреймворка

Между модулями — **абсолютные** импорты из `multiprocess_framework.modules.<name>`. Внутри одного модуля — **относительные** (`from ..interfaces import ...`).

## Добавление нового модуля

1. Создать `modules/<new_module>/` с обязательными файлами (см. [`docs/MODULE_README_TEMPLATE.md`](docs/MODULE_README_TEMPLATE.md)).
2. Добавить реэкспорт в `multiprocess_framework/__init__.py`.
3. Обновить `MODULES_STATUS.md`, `docs/MODULES_OVERVIEW.md`, `docs/MODULE_CONTRACTS.md`.
4. Архитектурные решения — `modules/<X>/DECISIONS.md` в формате `ADR-<КОД>-NNN` (реестр кодов — [`docs/ADR_REGISTRY.md`](docs/ADR_REGISTRY.md)).
5. Прогнать тесты: `python scripts/run_framework_tests.py`.
