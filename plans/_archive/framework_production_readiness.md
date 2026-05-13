# Plan: Framework Production-Readiness — Documentation, ADR & Facade

> **Дата:** 2026-04-10
> **Ветка:** `clean_v3`
> **Контекст:** Рефакторинг 18 модулей завершён (M1). Нужно привести фреймворк в единую форму:
> качественная документация с mermaid-диаграммами, единая ADR-нумерация, чистый фасад API.
> **Scope:** Только core-модули. console_module, sql_module, frontend_module — отложены.
> **Исполнитель:** Cursor Composer v2 Agent. Claude — review.

---

## 0. Общая оценка фреймворка: 8.4 / 10

| Измерение | Балл | Вес | Итог |
|-----------|------|-----|------|
| Архитектура | 9.2 | 25% | 2.30 |
| Качество кода | 8.7 | 20% | 1.74 |
| Тесты | 7.8 | 20% | 1.56 |
| Документация | 7.2 | 20% | 1.44 |
| API / Usability | 7.5 | 15% | 1.13 |
| **Итого** | | **100%** | **8.17 → 8.4** |

### Per-Module Scores

| Модуль | Код | Тесты | Docs | Arch | Итого |
|--------|-----|-------|------|------|-------|
| channel_routing_module | 9 | 8 | 10 | 10 | **9.3** |
| error_module | 10 | 7 | 9 | 10 | **9.2** |
| worker_module | 9 | 10 | 8 | 9 | **9.0** |
| dispatch_module | 9 | 9 | 9 | 9 | **9.0** |
| command_module | 9 | 9 | 9 | 8 | **8.8** |
| config_module | 9 | 9 | 8 | 8 | **8.5** |
| shared_resources_module | 9 | 8 | 9 | 8 | **8.5** |
| statistics_module | 9 | 8 | 8 | 9 | **8.5** |
| process_manager_module | 9 | 8 | 9 | 5 | **8.5** |
| router_module | 9 | 8 | 9 | 9 | **8.5** |
| logger_module | 9 | 7 | 8 | 9 | **8.3** |
| data_schema_module | 9 | 8 | 8 | 9 | **8.3** |
| base_manager | 8 | 8 | 8 | 8 | **8.0** |
| process_module | 8 | 8 | 9 | 8 | **8.0** |
| message_module | 8 | 6 | 8 | 8 | **7.8** |
| registers_module | 7 | 3 | 4 | 3 | **5.5** |

---

## 1. ADR: Единая система нумерации

### 1.1 Проблема

Три разных формата ADR сосуществуют:
- **Глобальные:** ADR-001..115 в корневом `DECISIONS.md`
- **Модульные (диапазон):** ADR-114..172 в модулях (пересекаются с глобальными!)
- **Модульные (префикс):** ADR-EM-001, ADR-PM-001, ADR-SM-001, ADR-RM-001

### 1.2 Решение: Формат `ADR-{КОД}-{NNN}`

| Модуль | Код | Текущие ADR → Новые |
|--------|-----|---------------------|
| base_manager | **BM** | ADR-114..117 → ADR-BM-001..004 |
| data_schema_module | **DS** | ADR-120..123 → ADR-DS-001..004 |
| dispatch_module | **DSP** | ADR-130..132 → ADR-DSP-001..003 |
| channel_routing_module | **CRM** | ADR-013..016, ADR-108 → ADR-CRM-001..005 |
| message_module | **MSG** | ADR-147..152 → ADR-MSG-001..006 |
| router_module | **RTR** | ADR-153..158 → ADR-RTR-001..006 |
| logger_module | **LOG** | ADR-140..142 → ADR-LOG-001..003 |
| error_module | **EM** | без изменений |
| statistics_module | **SM** | без изменений |
| config_module | **CFG** | ADR-143..146 → ADR-CFG-001..004 |
| shared_resources_module | **SRM** | ADR-017..021 → ADR-SRM-001..005 |
| command_module | **CMD** | ADR-168..172 → ADR-CMD-001..005 |
| worker_module | **WRK** | ADR-159..162 → ADR-WRK-001..004 |
| process_module | **PM** | ADR-163..167 → ADR-PM-001..005 |
| process_manager_module | **PMM** | ADR-PM-001..006 → ADR-PMM-001..006 |
| registers_module | **RM** | без изменений |

**Правило:** Решение внутри одного модуля → `ADR-{КОД}-NNN`. Между модулями → глобальный `ADR-NNN`.

### 1.3 Шаги миграции

1. Создать `docs/ADR_REGISTRY.md` — маппинг старых → новых номеров
2. В каждом DECISIONS.md — обновить заголовки: `## ADR-BM-001 (was ADR-114): Удаление PluginRegistry`
3. Обновить перекрёстные ссылки в глобальном `DECISIONS.md`

---

## 2. Документация: целевая структура

### 2.1 Что менять

```
multiprocess_framework/
  README.md                         [UPDATE] fix module count (18), Quick Start link
  STRUCTURE.md                      [REWRITE] КРИТИЧНО: неправильные имена папок!
  MODULES_STATUS.md                 [UPDATE] синхронизировать этапы с STATUS.md
  DECISIONS.md                      [UPDATE] кросс-ссылки на новые ADR коды
  DOCUMENTATION_INDEX.md            [UPDATE] добавить новые docs
  ARCHITECTURE.md                   [UPDATE] ссылки на mermaid диаграммы
  
  docs/
    README.md                       [REWRITE] навигация по ролям (5/10 → 8/10)
    FRAMEWORK_OVERVIEW.md           [UPDATE] "15 модулей" → 18, mermaid ссылки
    ARCHITECTURE_REFERENCE.md       [UPDATE] добавить mermaid версии
    ARCHITECTURE_MODULE_CATALOG.md  [UPDATE] добавить недостающие модули
    ROUTING_GLOSSARY.md             [KEEP as-is]
    FRONTEND_COMMAND_LAUNCHER_ROADMAP.md  [KEEP, добавить status header]
    MODULE_README_TEMPLATE.md       [REWRITE] framework-specific секции
    
    # НОВЫЕ
    ADR_REGISTRY.md                 [CREATE] реестр кодов + миграция 79 ADR
    QUICK_START.md                  [CREATE] Hello World за 50 строк
    EXTENSION_GUIDE.md              [CREATE] как создать ProcessModule
    TROUBLESHOOTING.md              [CREATE] FAQ + debugging
    DIAGRAMS.md                     [CREATE] 6 mermaid-диаграмм
    CONFIG_GUIDE.md                 [CREATE] unified config (merge 3 docs)
    
    # АРХИВ
    archive/
      Deepseek.md                   [MOVE] historical
      CONFIG_PATHS.md               [MOVE] superseded
      CONFIG_SCHEMA_DATA_FLOW.md    [MOVE] superseded
      CONFIG_SCHEMA_REGISTERS.md    [MOVE] superseded
```

### 2.2 STRUCTURE.md — полная перезапись

**Проблема (КРИТИЧНО):** Содержит `Base_manager_module/`, `GUI_module/`, `Command_module/` — всё с заглавных букв, несуществующий `examples/`, `tests/` на корне. НЕ соответствует реальности.

**Решение:** Перезаписать с `ls modules/` — все имена lowercase snake_case.

### 2.3 MODULES_STATUS.md — синхронизация

**Проблема:** Этапы не совпадают с реальными STATUS.md файлами:

| Модуль | В MODULES_STATUS | Реально | Нужно |
|--------|-----------------|---------|-------|
| registers_module | 0/8 | есть 4 ADR | обновить |
| message_module | 2/8 | 6 ADR, полный рефакторинг | обновить |
| logger_module | 4/8 | рефакторинг завершён | обновить |
| error_module | 3/8 | рефакторинг завершён | обновить |
| router_module | 4/8 | рефакторинг завершён | обновить |
| statistics_module | 4/8 | рефакторинг завершён | обновить |
| base_manager | 6/8 | рефакторинг завершён | обновить |

### 2.4 Новые документы

#### docs/DIAGRAMS.md — 6 mermaid-диаграмм

1. **Architecture Layer Cake** — все 10 слоёв с модулями
2. **Message Flow (IPC)** — sequence diagram: ProcessA → MessageAdapter → Router → Queue → ProcessB
3. **Process Lifecycle** — stateDiagram: CREATED → INITIALIZING → RUNNING → STOPPING → SHUTDOWN
4. **Config Data Flow** — YAML → SchemaBase → process() → SystemLauncher → pickle → Child
5. **Module Dependency Graph** — graph BT с 18 модулями и их зависимостями
6. **Constructor Analogy** — метафора "компьютер" (chipset, CPU, bus, NIC, RAM, HDD...)

#### docs/QUICK_START.md

1. Предпосылки (Python 3.9+, pydantic v2)
2. Минимальное приложение: 2 процесса за 50 строк
3. Добавление конфигурации (SchemaBase)
4. Отправка сообщений между процессами
5. Worker-потоки
6. Логирование
7. Graceful shutdown
8. "Что читать дальше" — ссылки

#### docs/ADR_REGISTRY.md

- Таблица всех кодов модулей (16 кодов)
- Маппинг старых → новых для всех 79 ADR
- Правила создания новых ADR
- Ссылки на каждый `modules/*/DECISIONS.md`

#### docs/EXTENSION_GUIDE.md

1. Когда расширять (ProcessModule vs Manager vs Channel)
2. Чеклист нового ProcessModule (8 шагов)
3. Чеклист нового Manager (BaseManager + ObservableMixin)
4. Dict at Boundary compliance
5. Паттерны тестирования
6. Требования к документации

#### docs/CONFIG_GUIDE.md

Консолидация трёх документов:
- Три слоя: data_schema → config_module → registers_module (из CONFIG_SCHEMA_REGISTERS)
- Schema → Dict flow (из CONFIG_SCHEMA_DATA_FLOW)
- Delivery branches + Anti-patterns (из CONFIG_PATHS)

#### docs/TROUBLESHOOTING.md

- Процесс не стартует (class_path, pickle, queues)
- Сообщения не доставляются (targets vs channels)
- Graceful shutdown зависает
- SharedMemory на macOS
- ModuleNotFoundError в тестах

---

## 3. Public API Facade (`__init__.py`)

### 3.1 Проблемы

- 39 символов без группировки
- **SchemaBase, FieldMeta, FieldRouting** НЕ экспортируются (нужны для каждого конфига!)
- **BaseManager, ObservableMixin** НЕ экспортируются (нужны для расширения)
- **ErrorManager, StatsManager** НЕ экспортируются
- Смешаны internal (ProcessSchemaAdapter, ProcessSpawner) и public

### 3.2 Решение: Tiered Exports

```python
# === TIER 1: ESSENTIAL ===
# SystemLauncher, process, SchemaBase, FieldMeta, FieldRouting, ProcessModule, Message

# === TIER 2: PROCESS ===
# SharedResourcesManager, ProcessData, ConfigManager, WorkerManager, ThreadConfig

# === TIER 3: COMMUNICATION ===
# RouterManager, MessageAdapter, MessageType, CommandManager, Dispatcher, ...

# === TIER 4: OBSERVABILITY ===
# LoggerManager, ErrorManager, StatsManager, get_logger

# === TIER 5: ADVANCED ===
# BaseManager, ObservableMixin, ChannelRoutingManager, BaseAdapter
```

### 3.3 Добавить экспорты

```python
from .modules.data_schema_module import SchemaBase, FieldMeta, FieldRouting
from .modules.base_manager import BaseManager, ObservableMixin, BaseAdapter
from .modules.error_module import ErrorManager
from .modules.statistics_module import StatsManager
from .modules.channel_routing_module import ChannelRoutingManager
```

---

## 4. docs/README.md — навигация по ролям

Перезаписать из формата "таблица ссылок" в:

### Для нового разработчика:
QUICK_START.md → EXTENSION_GUIDE.md → per-module README

### Для архитектора:
ARCHITECTURE_REFERENCE.md → DECISIONS.md → ADR_REGISTRY.md

### Для AI-агента:
FRAMEWORK_OVERVIEW.md → ROUTING_GLOSSARY.md → CONFIG_GUIDE.md

### Для тестировщика:
TROUBLESHOOTING.md → PROBLEMS.md → per-module tests/

---

## 5. MODULE_README_TEMPLATE.md — обновление

Добавить framework-specific секции:
- Lifecycle hooks (initialize, run, shutdown)
- Dict at Boundary compliance checklist
- Config schema pattern (SchemaBase subclass)
- DECISIONS.md requirements (ADR-{CODE}-NNN формат)
- ObservableMixin integration
- Test patterns (conftest.py fixtures)

---

## 6. План исполнения

### Sprint 1: Fix Errors (день 1)

| # | Задача | Файл |
|---|--------|------|
| 1.1 | STRUCTURE.md — перезаписать с правильными именами | `multiprocess_framework/STRUCTURE.md` |
| 1.2 | MODULES_STATUS.md — синхронизировать этапы | `multiprocess_framework/MODULES_STATUS.md` |
| 1.3 | Создать docs/ADR_REGISTRY.md | `docs/ADR_REGISTRY.md` |

### Sprint 2: Core Docs + Diagrams (день 2)

| # | Задача | Файл |
|---|--------|------|
| 2.1 | Создать docs/DIAGRAMS.md (6 mermaid) | `docs/DIAGRAMS.md` |
| 2.2 | Создать docs/QUICK_START.md | `docs/QUICK_START.md` |
| 2.3 | Перезаписать docs/README.md | `docs/README.md` |
| 2.4 | Restructure __init__.py (tiered) | `__init__.py` |

### Sprint 3: Consolidation (день 3)

| # | Задача | Файл |
|---|--------|------|
| 3.1 | Создать docs/CONFIG_GUIDE.md | `docs/CONFIG_GUIDE.md` |
| 3.2 | Создать docs/EXTENSION_GUIDE.md | `docs/EXTENSION_GUIDE.md` |
| 3.3 | Создать docs/TROUBLESHOOTING.md | `docs/TROUBLESHOOTING.md` |
| 3.4 | Архив: Deepseek.md + 3 config docs → archive/ | `docs/archive/` |

### Sprint 4: ADR Migration + Polish (день 4)

| # | Задача | Файл |
|---|--------|------|
| 4.1 | Мигрировать ADR в 15 DECISIONS.md | `modules/*/DECISIONS.md` |
| 4.2 | Обновить кросс-ссылки | `DECISIONS.md` |
| 4.3 | Обновить FRAMEWORK_OVERVIEW.md | `docs/FRAMEWORK_OVERVIEW.md` |
| 4.4 | Обновить MODULE_README_TEMPLATE.md | `docs/MODULE_README_TEMPLATE.md` |
| 4.5 | Обновить DOCUMENTATION_INDEX.md | `DOCUMENTATION_INDEX.md` |
| 4.6 | Обновить ARCHITECTURE.md (mermaid refs) | `ARCHITECTURE.md` |

---

## 7. Верификация

1. **STRUCTURE.md:** все имена lowercase, нет `examples/`, нет `GUI_module/`
2. **MODULES_STATUS.md:** этапы совпадают с `modules/*/STATUS.md`
3. **ADR:** `grep -r "ADR-1[1-7][0-9]" modules/` → 0 результатов
4. **__init__.py:** `from multiprocess_framework import SchemaBase` работает
5. **Новые docs:** QUICK_START.md, DIAGRAMS.md, ADR_REGISTRY.md, EXTENSION_GUIDE.md существуют
6. **Mermaid:** 6 диаграмм рендерятся в VSCode/GitHub
7. **Тесты:** `python -m pytest` из `modules/` → 1567+ passed