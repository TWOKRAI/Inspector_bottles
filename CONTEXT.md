## Project context
Generated: April 1, 2026 by [codebase-mcp](https://github.com/Dipanshu-js/codebase-mcp). Дерево каталогов синхронизировано с **user-codebase-mcp** (`get_context`, `get_structure`); обзор соглашений — `get_conventions` (слабые сигналы, детали в блоке Conventions ниже).

**Inspector_bottles** — инспекция бутылок / машинное зрение; основная разработка в ``.

### Ограничение MCP `get_context`
Инструмент **не подставляет** этот файл: он **пересканирует** репозиторий и генерирует Markdown заново (см. `codebase-mcp` → `generateMarkdown(scan)`). Поэтому в сыром ответе MCP строка **Stack → Language: JavaScript** — артефакт сканера для проектов без JS/TS-стека; для правды о стеке смотрите блок ниже и `pyproject.toml`.

### Source of truth для агента (ручной блок)
- **Язык:** Python 3 (не JavaScript; codebase-mcp по умолчанию путает стек без `package.json` фронта).
- **Пакет:** `inspector-prototype` **0.1.0** — `pyproject.toml`.
- **Фреймворк:** `multiprocess_framework/` — многопроцессный каркас (оркестрация, IPC, конфиги, логи, shared resources).
- **Точка входа приложения:** `multiprocess_prototype/main.py` (`SystemLauncher`, процессы через `data_schema_module.process`).
- **Документация фреймворка:** `multiprocess_framework/docs/` (`FRAMEWORK_OVERVIEW.md`, `ARCHITECTURE_REFERENCE.md`).
- **Журнал решений:** `multiprocess_framework/DECISIONS.md`.
- **Схемы регистров приложения:** в прототипе (`multiprocess_prototype` / `schemas`; `registers` в v2/v3), не внутри абстрактного «ядра» фреймворка.
- **Правила репозитория:** `.cursor/rules/framework-architecture.mdc`.
- **Валидация:** `python scripts/validate.py` (из корня репозитория; при смене cwd см. README скрипта).
- **Тесты фреймворка (модули):** `python scripts/run_framework_tests.py` из текущий каталог, либо `cd multiprocess_framework/modules` и `python -m pytest` — см. `multiprocess_framework/README.md` (Testing).

## Stack
- Language: **Python** (`requires-python >=3.9`; зависимости: Pydantic, SQLAlchemy, NumPy, PyQt5, OpenCV, Pillow — см. `pyproject.toml`)
- Domain: **multiprocess desktop / vision pipeline** (camera, processor, renderer, robot, DB, GUI)
- Config / typing: **Pydantic внутри процессов**; **только `dict` на границе процессов** (Dict at Boundary)

## Structure
```
├── .cursor/  # 3 files
│   ├── plans/  # 5 files
│   ├── rules/  # 3 files
│   └── mcp.json
├──   # 12 files
│   ├── App/  # 11 files
│   │   ├── Core/  # 10 files
│   │   ├── Data/  # 4 files
│   │   ├── docs/  # 10 files
│   │   ├── Registers/  # 8 files
│   │   └── UI/  # 4 files
│   ├── hikvision_camera_module/  # 11 files
│   │   ├── adapters/  # 3 files
│   │   ├── core/  # 5 files
│   │   ├── sdk/  # 18 files
│   │   ├── sdk_app/  # 3 files
│   │   └── tests/  # 4 files
│   ├── multiprocess_framework/  # 14 files
│   │   ├── core/  # 1 files
│   │   ├── docs/  # 10 files
│   │   ├── logs/  # 3 files
│   │   ├── modules/  # 32 files
│   │   ├── tests/  # 7 files
│   │   └── tools/  # 3 files
│   ├── multiprocess_prototype/  # 18 files
│   │   ├── archive/  # 4 files
│   │   ├── backend/  # 9 files
│   │   ├── data/  # 2 files
│   │   ├── docs/  # 6 files
│   │   ├── frontend/  # 13 files
│   │   ├── logs/  # 16 files
│   │   ├── managers/  # 8 files
│   │   ├── persistence/  # 5 files
│   │   ├── schemas/  # 8 files
│   │   ├── stage_reports/  # 1 files
│   │   ├── tests/  # 35 files
│   │   └── utils/  # 5 files
│   ├── multiprocess_prototype_v2/  # 11 files
│   │   ├── backend/  # 9 files
│   │   ├── data/  # 2 files
│   │   ├── frontend/  # 13 files
│   │   ├── logs/  # 12 files
│   │   ├── managers/  # 8 files
│   │   ├── persistence/  # 5 files
│   │   ├── registers/  # 9 files
│   │   └── utils/  # 5 files
│   ├── multiprocess_prototype/  # 8 files
│   │   ├── backend/  # 9 files
│   │   ├── docs/  # 0 files
│   │   ├── frontend/  # 13 files
│   │   ├── logs/  # 0 files
│   │   └── registers/  # 8 files
│   ├── scripts/  # 5 files
│   ├── Services/  # 4 files
│   │   ├── hikvision_camera/  # 1 files
│   │   └── Region_processors/  # 5 files
│   ├── Utils/  # 11 files
│   │   ├── file_comments/  # 12 files
│   │   └── fps_module/  # 8 files
│   ├── pyproject.toml
│   └── UNIFICATION_PLAN.md
├── logs/  # 0 files
├── venv/  # 6 files
│   ├── etc/  # 1 files
│   │   └── jupyter/  # 1 files
│   ├── Include/  # 1 files
│   │   └── site/  # 1 files
│   ├── Lib/  # 1 files
│   │   └── site-packages/  # 177 files
│   ├── Scripts/  # 43 files
│   ├── share/  # 2 files
│   │   ├── jupyter/  # 3 files
│   │   └── man/  # 1 files
│   └── pyvenv.cfg
├── .cursorignore
├── .DS_Store
├── .gitignore
├── CONTEXT.md
├── GIT_WORKFLOW_BEGINNER.md
├── promt.md
└── README.md
```

## Conventions (репозиторий)
Ответ **user-codebase-mcp** `get_conventions` для этого дерева: без устойчивых алиасов/barrel-экспортов (`componentNaming`/`fileNaming`: unknown). Для работы в репозитории используйте правила фреймворка:

- **Импорты:** относительные внутри модуля фреймворка; между модулями — абсолютные (`multiprocess_framework.modules...`).
- **Публичный контракт модуля:** `interfaces.py`; README и `STATUS.md` по шаблону в `docs/`.
- **Тесты:** `pytest`, файлы `test_*.py` в `tests/` модулей.
- **Production:** не использовать `sys.path.insert` (проверяется `validate.py`).
- **Прочее:** см. `multiprocess_framework/docs/` и `.cursor/rules/`.

---
*Generated by [codebase-mcp](https://github.com/Dipanshu-js/codebase-mcp) — paste this into any AI tool. Ручной блок «Source of truth» выше поддерживать при смене архитектуры.*
