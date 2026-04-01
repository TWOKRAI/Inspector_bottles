## Project context
Generated: April 1, 2026 by [codebase-mcp](https://github.com/Dipanshu-js/codebase-mcp)

**Inspector_bottles** — инспекция бутылок / машинное зрение; основная разработка в `Inspector_prototype/`.

### Ограничение MCP `get_context`
Инструмент **не подставляет** этот файл: он **пересканирует** репозиторий и генерирует Markdown заново (см. `codebase-mcp` → `generateMarkdown(scan)`). Поэтому в ответе MCP строка **Stack → Language: JavaScript** — артефакт сканера для проектов без JS/TS-стека; для правды о стеке смотрите блок ниже и `pyproject.toml` / `requirements.txt`.

### Source of truth для агента (ручной блок)
- **Язык:** Python 3 (не JavaScript; codebase-mcp по умолчанию путает стек без `package.json` фронта).
- **Фреймворк:** `Inspector_prototype/multiprocess_framework/` — многопроцессный каркас (оркестрация, IPC, конфиги, логи, shared resources).
- **Точка входа приложения:** `Inspector_prototype/multiprocess_prototype/main.py` (`SystemLauncher`, процессы через `data_schema_module.process`).
- **Документация фреймворка:** `Inspector_prototype/multiprocess_framework/docs/` (`FRAMEWORK_OVERVIEW.md`, `ARCHITECTURE_REFERENCE.md`).
- **Схемы регистров приложения:** в прототипе (`multiprocess_prototype` / `registers`), не внутри абстрактного «ядра» фреймворка.
- **Правила репозитория:** `.cursor/rules/framework-architecture.mdc`.
- **Валидация:** `python Inspector_prototype/scripts/validate.py` (из корня `Inspector_prototype` или согласно README скрипта).

**Inspector_bottles** vunknown (версия из `pyproject.toml` / пакета при необходимости уточнять)

## Stack
- Language: **Python**
- Domain: **multiprocess desktop / vision pipeline** (camera, processor, renderer, robot, DB, GUI)
- Config / typing: **Pydantic внутри процессов**; **только `dict` на границе процессов** (Dict at Boundary)

## Structure
```
├── .cursor/  # 2 files
│   ├── plans/  # 5 files
│   └── rules/  # 3 files
├── archive/  # 4 files
│   ├── examples/  # 8 files
│   ├── modules (no work!!!) go refactored/  # 16 files
│   │   ├── Base_manager_module/  # 9 files
│   │   ├── Command_module/  # 6 files
│   │   ├── Component_data_module/  # 1 files
│   │   ├── Config_module/  # 4 files
│   │   ├── Console_module/  # 6 files
│   │   ├── Dispatch_module/  # 9 files
│   │   ├── GUI_module/  # 4 files
│   │   ├── Logger_module/  # 12 files
│   │   ├── Message_module/  # 5 files
│   │   ├── Process_manager_module/  # 18 files
│   │   ├── Process_module/  # 9 files
│   │   ├── Router_module/  # 7 files
│   │   ├── Shared_resources_module/  # 9 files
│   │   └── Worker_module/  # 3 files
│   ├── Multiproccesing/  # 5 files
│   │   └── Processes/  # 11 files
│   └── REGISTERS_APPROACH_ANALYSIS.md
├── BASKET/  # 28 files
│   ├── App/  # 5 files
│   │   ├── Components/  # 1 files
│   │   ├── Threads/  # 1 files
│   │   ├── Widget/  # 4 files
│   │   └── Windows/  # 1 files
│   ├── App2/  # 2 files
│   │   ├── Components/  # 1 files
│   │   └── Widget/  # 4 files
│   ├── BasicDemo/  # 1 files
│   ├── Camera_module2/  # 4 files
│   ├── Create_bottles/  # 15 files
│   │   └── Images/  # 11 files
│   ├── Data/  # 4 files
│   │   ├── debug_logs/  # 1 files
│   │   └── Recipes/  # 1 files
│   ├── dataset/  # 2 files
│   │   ├── bad/  # 4 files
│   │   └── good/  # 2 files
│   ├── Inspector_backup_worker/  # 22 files
│   │   ├── App/  # 8 files
│   │   ├── Bot/  # 3 files
│   │   ├── Devices/  # 4 files
│   │   ├── Display_robot/  # 2 files
│   │   ├── Multiproccesing/  # 5 files
│   │   ├── Neuron/  # 12 files
│   │   ├── Process_image/  # 4 files
│   │   └── Utils/  # 7 files
│   ├── logs/  # 1 files
│   ├── modules (no work!!!) go refactored/  # 14 files
│   │   ├── Base_manager_module/  # 1 files
│   │   ├── Command_module/  # 1 files
│   │   ├── Config_module/  # 1 files
│   │   ├── Console_module/  # 1 files
│   │   ├── Dispatch_module/  # 2 files
│   │   ├── GUI_module/  # 1 files
│   │   ├── Logger_module/  # 1 files
│   │   ├── Message_module/  # 1 files
│   │   ├── Process_manager_module/  # 11 files
│   │   ├── Process_module/  # 1 files
│   │   ├── Router_module/  # 1 files
│   │   ├── Shared_resources_module/  # 2 files
│   │   └── Worker_module/  # 1 files
│   ├── Multiproccesing/  # 10 files
│   │   ├── process_module_new/  # 2 files
│   │   ├── process_module_new2/  # 10 files
│   │   ├── Process_modules/  # 10 files
│   │   └── Processes/  # 8 files
│   ├── Neuron/  # 1 files
│   │   └── Data_image/  # 4 files
│   ├── Services/  # 5 files
│   │   ├── graph/  # 2 files
│   │   ├── hikvision_camera/  # 9 files
│   │   └── Operation_crop/  # 4 files
│   ├── Test_bottle/  # 5 files
│   │   └── Images/  # 10 files
│   ├── Utils/  # 7 files
│   ├── Visualization/  # 2 files
│   ├── color_process.py
│   ├── combine_files.py
│   ├── combined_code_anton.txt
│   ├── combined_code.txt
│   ├── frame_test2.jpg
│   ├── launcher.bat
│   ├── main.pyw
│   ├── plot_numpy.png
│   ├── test.py
│   ├── value_settings.xlsx
│   └── value.dat
├── Inspector_prototype/  # 14 files
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
│   ├── inspector_prototype.egg-info/  # 5 files
│   ├── logs/  # 4 files
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
│   ├── multiprocess_prototype_v3/  # 8 files
│   │   ├── backend/  # 9 files
│   │   ├── docs/  # 0 files
│   │   ├── frontend/  # 13 files
│   │   ├── logs/  # 0 files
│   │   └── registers/  # 8 files
│   ├── scripts/  # 5 files
│   ├── Services/  # 5 files
│   │   ├── hikvision_camera/  # 1 files
│   │   ├── Operation_crop/  # 9 files
│   │   └── Region_processors/  # 5 files
│   ├── Utils/  # 11 files
│   │   ├── file_comments/  # 12 files
│   │   └── fps_module/  # 8 files
│   ├── pyproject.toml
│   └── UNIFICATION_PLAN.md
├── logs/  # 4 files
│   ├── critical.log
│   ├── errors.log
│   ├── stats_TestStats.json
│   └── warnings.log
├── Neuron/  # 1 files
│   └── Data_image/  # 4 files
│       ├── Data_all/  # 0 files
│       ├── Data_bad/  # 0 files
│       ├── Data_good/  # 0 files
│       └── Data_none/  # 0 files
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
├── camera.log
├── database.log
├── frames.log
├── GIT_WORKFLOW_BEGINNER.md
├── gui.log
├── messages.log
├── processor.log
├── promt.md
├── README.md
├── renderer.log
├── requirements.txt
├── robot.log
└── system.log
```

## Conventions (репозиторий)
- **Импорты:** относительные внутри модуля фреймворка; между модулями — абсолютные (`multiprocess_framework.modules...`).
- **Публичный контракт модуля:** `interfaces.py`; README и `STATUS.md` по шаблону в `docs/`.
- **Тесты:** `pytest`, файлы `test_*.py` в `tests/` модулей.
- **Production:** не использовать `sys.path.insert` (проверяется `validate.py`).
- **Прочее:** см. `Inspector_prototype/multiprocess_framework/docs/` и `.cursor/rules/`.

---
*Generated by [codebase-mcp](https://github.com/Dipanshu-js/codebase-mcp) — paste this into any AI tool. Ручной блок «Source of truth» выше поддерживать при смене архитектуры.*