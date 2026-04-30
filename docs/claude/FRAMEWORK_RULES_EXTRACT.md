# Выжимка документации Multiprocess Framework (для сокращения под правила)

Источники: `multiprocess_framework/README.md`, `DOCUMENTATION_INDEX.md`, `MODULES_STATUS.md`, `PROBLEMS.md`, `DECISIONS.md` (оглавление + суть ключевых ADR), `docs/*`, `modules/*/README.md` (корневые README пакетов модулей).

**Нарратив «фреймворк как конструктор»** (таблица модулей + поток сборки, выверено под README/ADR): [`.claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md`](FRAMEWORK_CONSTRUCTOR_OVERVIEW.md).

---

## 1. Где что лежит

| Что | Путь |
|-----|------|
| Корень фреймворка | `multiprocess_framework/` |
| Модули (код) | `modules/<name>/` |
| Обзор, глоссарий, конфиг-потоки | `docs/FRAMEWORK_OVERVIEW.md`, `docs/ROUTING_GLOSSARY.md`, `docs/CONFIG_SCHEMA_DATA_FLOW.md`, `docs/CONFIG_PATHS.md`, `docs/CONFIG_SCHEMA_REGISTERS.md`, `docs/ARCHITECTURE_REFERENCE.md` |
| ADR | `DECISIONS.md` (сортировка по ADR-NNN; устаревшее в отдельном разделе) |
| Сводный статус модулей | `MODULES_STATUS.md`; детали — всегда `modules/<name>/STATUS.md` |
| Известные ограничения | `PROBLEMS.md`, `tests/integration/TEST_ISSUES.md` |

**Тестовое приложение-прототип** (не ядро фреймворка): `multiprocess_prototype/` и др.; **схемы регистров приложения** живут в приложении (например `registers/schemas`), не в пакете фреймворка (ADR-050).

---

## 2. Слои и модули (рабочая модель)

**Foundation:** `base_manager`, `data_schema_module`, `message_module`  
**Infrastructure:** `logger_module`, `error_module`, `config_module`, `console_module`, `shared_resources_module`, `registers_module`, `sql_module`  
**Communication:** `dispatch_module`, `router_module`, `command_module`  
**Process:** `worker_module`, `process_module`  
**Orchestration:** `process_manager_module`  
**Frontend:** `frontend_module`  

**Дополнительно в дереве:** `channel_routing_module` (CRM — база для Router/Logger/Error/Stats), `statistics_module`.

Точка входа оркестрации: **`SystemLauncher`** (`process_manager_module/launcher/system_launcher.py`). Базовый класс процесса приложения: **`ProcessModule`**.

---

## 3. Правила, которые агент обязан соблюдать при работе с фреймворком

1. **Dict at Boundary (ADR-008)**  
   Между процессами — только **pickle-safe `dict`**. Сообщения: `Message.to_dict()` / `Message.from_dict()`. Внутри процесса — Pydantic/`SchemaBase` допустимы.

2. **Публичный контракт модуля**  
   Зависимости между модулями — через **`interfaces.py`** целевого модуля; не протаскивать внутренние `core/` в чужие пакеты.

3. **Структура модуля (ожидаемая)**  
   `interfaces.py`, `README.md`, `STATUS.md`, `tests/` (pytest, `test_*.py`).

4. **`sys.path.insert` в production-коде** — не использовать (валидация: `python scripts/validate.py` из текущий каталог).

5. **Конфиг на границе**  
   Принимать **`dict`**; Pydantic — внутри модуля. Сборка процессов: схемы → `process()` / `model_dump` — см. ADR-102, ADR-104, ADR-105 и `docs/CONFIG_*`.

6. **Импорты в unit-тестах модулей**  
   Под `modules/` — **плоские** имена пакетов (`from data_schema_module import ...`). Рабочий каталог pytest: **`multiprocess_framework/modules`** или скрипт `python scripts/run_framework_tests.py` из текущий каталог. Без `PYTHONPATH` запуск из корня часто даёт `ModuleNotFoundError`.

7. **Логи (ADR-111)**  
   Пути логов не привязаны к cwd исходников; env `MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`, в pytest — изолированный temp через `conftest.py`.

8. **Архитектурные изменения**  
   Фиксировать в **`DECISIONS.md`**. После изменений модуля — обновить **`STATUS.md`** модуля.

9. **Полный прогон**  
   Из текущий каталог: `python scripts/validate.py` и `python scripts/run_framework_tests.py`.

---

## 4. Сообщения и маршрутизация (суть)

- **Типы сообщений** (`message_module`): GENERAL, COMMAND, LOG, SYSTEM, BROADCAST, DATA, REQUEST, RESPONSE, EVENT.  
- **Создание:** предпочтительно **`MessageAdapter`** (фиксирует `sender`).  
- **Request/response (ADR-005):** `correlation_id` / `request_id`, `reply_to`.  
- **Команды:** `command_module` = обёртка над `dispatch_module`; ключ по полю **`command`**, данные в **`data`** / `args` по контракту сообщения.  
- **Router:** исходящие — каналы (`msg["channel"]`, диспетчер), **`AsyncSender`**; входящие — **`message_dispatcher`** + callbacks.  
- **Не путать:** имя **процесса** (`targets`, `send_message(target, ...)`) и строку **канала Router** (`FieldRouting.channel`). См. **`docs/ROUTING_GLOSSARY.md`**: `connection_map`, `register_dispatch`, `process_targets`, fan-out.

---

## 5. Shared resources (SRM)

- **Pickle-safe** передача в дочерние процессы; после unpickle — **`reinitialize_in_child()`** (ADR-020).  
- Регистрация процессов — **`register_process()`** как единая точка (ADR-018).  
- **`ConfigStore` отдельно от `ProcessData`** (ADR-017).  
- В коде процесса настройки читать через **`ProcessModule.get_config`** / фасад конфига, а не вручную ковырять bundle (см. `docs/CONFIG_PATHS.md`).

---

## 6. MODULES_STATUS.md — что запомнить

- Сводная таблица этапов 8/8 и оценок по модулям; **истина по деталям** — в `modules/*/STATUS.md`.  
- **registers_module** в сводке на низком этапе документации/тестов — при изменениях сверяться с `STATUS.md` модуля.  
- CRM unification (фазы 1–5) завершена; Router/Logger/Error на базе **`channel_routing_module`**.

---

## 7. PROBLEMS.md — кратко

- Unit-тесты фреймворка: OK; **MemoryManager** — skip на macOS (SharedMemory).  
- **Pydantic:** предупреждение про `model_fields` на инстансе в `data_schema_module` — канон: **`self.__class__.model_fields`**.  
- Прототип v3 / кросс-импорты v2 — ожидаемое трение до выноса общего слоя приложения.

---

## 8. Ключевые ADR (имена из оглавления DECISIONS.md)

| ADR | Суть |
|-----|------|
| 001 | **ObservableMixin** остаётся (связка logger/stats/error). |
| 002 | **registers_module** отдельно от **data_schema** (runtime ≠ статическая схема). |
| 003 | Схемы — «живое ДНК», не выбрасываются после build. |
| 004 | Синхронизация структуры через connection bundle; живые значения — у хозяина процесса. |
| 005 | Request-response через **correlation_id**. |
| 008 | **Dict at Boundary**. |
| 013–016 | **channel_routing_module**, IChannel, AsyncSender в Router, ChannelRoutingConfig. |
| 017–021 | ConfigStore, register_process, SharedMemory по именам, pickle SRM, reinitialize_in_child. |
| 022 | **StatsManager** наследует CRM, не LoggerManager. |
| 023 | **config_module** — тонкая обёртка над data_schema (валидация там). |
| 032 | **sql_module** — универсальный SQL (SQLAlchemy 2.0), команды через процесс БД / роутер. |
| 033–037+ | frontend: FrontendManager, FrontendRegistersBridge, hot-reload, MVP вкладок, controls v2 — смотреть DECISIONS при правках UI. |
| 048 | Доставка **register_update**, RegisterDispatchMeta, fan-out. |
| 050 | Схемы регистров — в **приложении**. |
| 102–111 | Канон schema→dict, конфиги модулей на SchemaBase, пути логов, публичный API пакета (ADR-115). |

Полный текст и «Устарело» — только в **`DECISIONS.md`**.

---

## 9. По модулям — самое важное из README

### base_manager
**BaseManager** (жизненный цикл, адаптеры, события) + **ObservableMixin** (`_log_*`, `_record_metric`, `_track_error`). База для менеджеров.

### message_module
Единый протокол сообщений; **граница — dict**; **`MessageAdapter`** для создания; типы и поля — в README таблицами.

### data_schema_module
**SchemaBase**, **FieldMeta**, **FieldRouting** (канал Router + опционально `process_targets`), **RegisterDispatchMeta** / `register_dispatch` на классе регистра; сериализация, контейнеры, реестр. **Независимое ядро** (без зависимостей на другие модули фреймворка).

### channel_routing_module
**ChannelRoutingManager**: единый **ChannelRegistry**, диспетчер, буферизация (**IBufferStrategy**), `normalize_config`. База для Logger / Error / Router / Stats.

### logger_module
**LoggerManager(CRM)**: scope-based маршрутизация, **BatchBuffer**, каналы **ILogChannel**; интеграция через ObservableMixin.

### error_module
**ErrorManager(LoggerManager)**: level-based файлы (critical/errors/warnings), **`log_exception`**.

### config_module
Runtime: dot-notation, подписки, env-fallback, синхронизация с **ConfigStore**; валидация — в **data_schema_module**.

### console_module
Терминальный I/O; не логгер и не роутер; уровни passive / active / God Mode; **ConsoleAdapter** к ProcessModule.

### shared_resources_module
**SharedResourcesManager**: очереди, события, память, **ConfigStore**; pickle-safe; **`register_process`**, **`reinitialize_in_child`**.

### router_module
**RouterManager(CRM)**: **AsyncSender**, `channel_dispatcher` + **`message_dispatcher`** для входящих, **QueueChannel** и др.

### dispatch_module
**Dispatcher**: стратегии EXACT / FALLBACK / PATTERN / CHAIN; `register_handler` / `dispatch`.

### command_module
**CommandManager** = командный API над Dispatcher: `register_command`, `handle_command`, ключ **`command`**.

### worker_module
Потоки внутри процесса: **WorkerManager**, **ThreadConfig**, **ExecutionMode** (LOOP / TASK и др.), stop/pause events.

### process_module
**ProcessModule**: композиция менеджеров, воркеры, роутер, команды; **`get_config`** / `config_handler` как фасад; жизненный цикл `initialize` / `run` / `shutdown`.

### process_manager_module
**SystemLauncher**, **ProcessManagerProcess**, реестр процессов, мониторинг, graceful shutdown; **Dict at Boundary** на входе лаунчера; встроенные команды process/system.

### registers_module
Runtime **RegistersManager**, **`build_connection_map_from_registers`**, routing map и отправка сообщений по регистрам; классы схем — из приложения.

### sql_module
**SQLManager**: SQLAlchemy 2.0, UoW, репозитории, **`execute_command`** для интеграции с CommandManager; БД обычно в отдельном процессе, доступ по каналу **`database`** / командам `db.*`.

### statistics_module
**StatsManager(CRM)**: counter/gauge/timing/histogram; двойное хранение + flush в каналы; sentinel против N-кратного счёта при нескольких каналах.

### frontend_module
**FrontendManager**, **FrontendRegistersBridge**, **RoutedCommandSender**; схемы регистров подставляет приложение; config hot-reload через config_module.

---

## 10. Документы docs/ — зачем открывать

| Файл | Когда |
|------|--------|
| FRAMEWORK_OVERVIEW.md | Целостная картина, паттерны, FAQ |
| ARCHITECTURE_REFERENCE.md | Таблицы, матрицы зависимостей |
| ROUTING_GLOSSARY.md | Путаница process vs channel, fan-out |
| CONFIG_SCHEMA_DATA_FLOW.md, CONFIG_PATHS.md, CONFIG_SCHEMA_REGISTERS.md | Цепочка схема → dict → процесс / регистры |
| ARCHITECTURE_MODULE_CATALOG.md | Каталог пакетов |
| MODULE_README_TEMPLATE.md | Новый модуль |

---

*Файл предназначен для ручного сжатия под `.claude/CLAUDE.md` или отдельное правило Cursor; дата сборки конспекта: 2026-04-06.*
