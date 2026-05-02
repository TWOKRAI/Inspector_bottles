# Профессиональная оценка фреймворка — обновление 2026-05-02

**Аудитор:** независимый ревью после правок Phase 2 (state_store / chain / ProcessStatus unification / ObservableMixin refactor / frontend reorg).
**База оценки:** 21 модуль (+2 с прошлой ревизии), ~80 000 LOC, ~2 000 проходящих тестов, актуализированный qex-индекс (1 879 файлов, 17 516 чанков, dense+BM25).
**Связанные документы:** [`ASSESSMENT.md`](ASSESSMENT.md) (предыдущая, 2026-04-25), [`PROBLEMS.md`](PROBLEMS.md), [`docs/CONSTRUCTOR_BLUEPRINT.md`](docs/CONSTRUCTOR_BLUEPRINT.md).

> **Формат:** изменение оценки относительно прошлого ревью + новая дельта. Затем — список рекомендаций по приоритетам.

---

## Свод оценок (дельта к 2026-04-25)

| Раздел | Было | Стало | Δ | Комментарий |
|--------|-----:|------:|---|-------------|
| 1. Концепция и идея | 9 / 10 | **9 / 10** | = | Без изменений — формулировка зрелая. |
| 2. Архитектурный замысел | 9 / 10 | **9 / 10** | = | Граф зависимостей чист. Появились state_store / chain — логично легли в L5/L6. |
| 3. Качество реализации | 7.5 / 10 | **8 / 10** | +0.5 | Унифицирован `ProcessStatus` (ADR-117), завершён рефакторинг ObservableMixin, frontend reorg Phase 2 финиширован. |
| 4. Тестовое покрытие | 8 / 10 | **8 / 10** | = | Добавлены тесты state_store (~415) и chain (~60); общая ratio ~0.47 удержана. 2 known-failing на месте. |
| 5. Документация | 8.5 / 10 | **8 / 10** | −0.5 | Документация частично рассинхронизирована: `MODULE_CONTRACTS.md` заявляет «19 модулей», по факту 21; `DIAGRAMS.md` не обновлён под state_store/chain; корневой `__init__.py` не экспортирует state_store/chain/sql/frontend. |
| 6. Производительность | 7 / 10 | **7 / 10** | = | По-прежнему нет performance-baseline. |
| 7. Кросс-платформенность | 7 / 10 | **7 / 10** | = | Без CI matrix верифицировать невозможно. |
| 8. Обслуживаемость | 8 / 10 | **8 / 10** | = | Структура модулей выдерживает прирост; но `data_schema_module` (16K) и `frontend_module` (12K) растут. |
| 9. Готовность к проду | 8 / 10 | **8 / 10** | = | Без CI/benchmark — лабораторный уровень. |
| 10. Соответствие декларации | 9 / 10 | **8 / 10** | −1 | Корневой фасад не отражает реальное число модулей: 5 «новых» модулей доступны только по полному пути. Декларация «49 экспортов» актуальна, но не охватывает state_store, chain, sql, frontend. |

**Общая оценка: 8.0 / 10** (было 8.1) — лёгкое снижение из-за документационного и фасадного дрейфа после ввода новых модулей. Архитектурно — продолжает усиливаться.

---

## Что изменилось с 2026-04-25 (положительное)

1. **`ProcessStatus` унифицирован.** Был тройной enum (`process_module`, `shared_resources_module`, `process_manager_module/core`); теперь — единый источник в `multiprocess_framework/modules/base_manager/types/process_status.py` с 9 значениями. ADR-117 зафиксирован, тесты `test_process_status_unified.py` проходят. **Резолюция предыдущей рекомендации Tier-2 №4.**
2. **Добавлен `state_store_module`.** Реактивное дерево состояния со server/client разделением (server в `ProcessManagerProcess`, клиенты в каждом процессе). Решает целый класс задач, которые ранее «размазывались» по `ConfigStore` и broadcast-сообщениям. Зависит только от `base_manager`. Использует `IRouter` как Protocol — тестируется без IPC через `InMemoryRouter`. ~415 тестов, middleware-pipeline (`Throttle`/`Validation`/`Logging`/`Metrics`), `Selector`, `RecipeEngine`, `PersistenceManager`. Зрелое решение.
3. **Добавлен `chain_module`.** DAG-движок для pipeline-обработки кадров: `ChainRunnable` / `DagRunnable` / `ParallelChainRunnable` + `WorkerPoolDispatcher` (cross-process round-robin с backpressure). Standalone — не зависит от других модулей фреймворка. Чёткие границы (builder и операции — в прикладном коде).
4. **`ObservableMixin` рефакторинг завершён.** В прототипе и фреймворке устранены прямые `import logging`. Все менеджеры пишут через `_log_*`/`_record_*`/`_track_*`.
5. **Frontend Phase 2 завершён** (по логам коммитов от 2026-04). Виджеты сгруппированы по доменам (`chrome/`, `sources/`, `recipes/`, `processing/`, `settings/`, `pipeline/`, `tabs_setting/`, `base/`).
6. **`ProcessManagerProcess` получил расширительные хуки.** Появились `_setup_console_manager`, `_setup_topology_manager`, `_setup_state_store` — переопределяются в прикладном коде без модификации фреймворка. Это правильное направление: framework — open for extension, closed for modification.
7. **`SystemLauncher.wait_until_ready()`** (ADR-116) — Event-based ожидание готовности системы. Полезно в e2e-тестах и в скриптах автозапуска.

## Что ухудшилось / выявлено впервые

### Tier 1 — блокирует промышленный релиз

1. **Документация рассинхронизирована.**
   - `docs/MODULE_CONTRACTS.md` — заголовок «контракты 19 модулей», по факту 21. Секции для `state_store_module` и `chain_module` есть, но сводная таблица в конце ссылается на 19. Сводная таблица не содержит state_store, chain.
   - `docs/DIAGRAMS.md` — диаграмма «Module dependency graph (19 packages)»; в ней нет state_store, chain. Слой L5 на диаграмме не показывает state_store.
   - `MODULES_STATUS.md` — заявляет «21 пакет», но `STRUCTURE.md` пишет «всего пакетов под `modules/`: 19». В `__init__.py` `__all__` написано «49 экспортов», но реально экспортируется ~46 (часть символов не вошли при добавлении новых модулей).

2. **Корневой фасад `multiprocess_framework/__init__.py` не отражает state_store, chain, sql, frontend.**
   ```python
   # из multiprocess_framework импортируется только:
   #   base, schema, message, dispatch, crm, router, logger, error, stats,
   #   config, srm, command, worker, console, process, pmgr, registers
   # state_store, chain, sql, frontend — только по полному пути
   from multiprocess_framework.modules.state_store_module import StateStoreManager
   from multiprocess_framework.modules.chain_module import ChainRunnable
   from multiprocess_framework.modules.sql_module import SQLManager
   from multiprocess_framework.modules.frontend_module import FrontendManager
   ```
   Это **фасадный дрейф**: пользователь должен знать, какие модули «свежие» и требуют полного пути, а какие — старые и доступны с корня. Это противоречит R-1 (каноничные импорты).

3. **`ProcessStatusMonitor` алиасится как `ProcessStatus`** в `process_manager_module/core/process_status.py:111` (`ProcessStatus = ProcessStatusMonitor` — backward-compat по ADR-117). Это создаёт **семантический конфликт**: `ProcessStatus` в одном модуле — `Enum` (статус), в другом — `class` (мониторинг). Backward-compat алиас оставлен «временно», но без чёткого срока удаления — превращается в ловушку для будущих ревью.

4. **2 failing-теста** живы с 2026-04-25 (`test_init_creates_components`, `test_console_process_config_build_and_process_helper`). Зелёная зона CI остаётся декларацией, не гарантией. Любой `pytest` без `--ignore` завершится с ненулевым кодом.

### Tier 2 — системные риски

5. **`ProcessManagerProcess` превращается в god-class.** Уже инициализирует: `ProcessRegistry`, `ProcessPriority`, `ProcessStatusMonitor`, `ProcessMonitor`, `ConsoleManager`, `TopologyManager`, `StateStoreManager`, `EventManager` (через ProcessModule). 13 встроенных команд (`process.list/create/start/stop/pause/resume/restart/status`, `system.shutdown/stats`, `topology.apply/get/diff`). При следующих 2-3 фичах — трудно будет тестировать целиком.

6. **Двойной dispatch путь** между `CommandManager` и `RouterManager.message_dispatcher`. После `ProcessLifecycle._register_commands_with_router` каждая команда регистрируется и в `command_manager.dispatcher`, и в `router_manager.message_dispatcher`. Это **два индекса для одной таблицы**: при рассогласовании (handler удалён в одном, остался в другом) поведение непредсказуемо. На граничных кейсах ловить будет тяжело.

7. **Два comm-API на ProcessModule** — `send_message(target, msg) -> bool` и `send(msg) -> dict` (ADR-163). Оба активно используются. С точки зрения учения — лишний выбор для разработчика. Кандидат на унификацию: `send` возвращает `dict` со статусом, `send_message` оставить как тонкую обёртку или удалить.

8. **`data_schema_module` 16 168 LOC** — самый большой модуль; внутри есть `tools/`, `extensions/`, `builders/`, `validators/`, `ui/`. Разбить на под-пакеты: `data_schema_core/` (SchemaBase + FieldMeta + FieldRouting), `data_schema_runtime/` (SchemaRegistry + RegistersContainer + DataConverter), `data_schema_tools/` (документатор, генератор UI-метаданных). Иначе через 6-12 месяцев — экспоненциальный рост.

9. **`frontend_module` 12 039 LOC** — один из самых сложных модулей. Хотя структура виджетов формализована (Phase 2 завершён), модуль остаётся внутри фреймворка. Остаётся валидным предложение: вынести в `frontend_framework/` как опциональный пакет с зависимостью на `multiprocess_framework`.

10. **Rosсыпь алиасов в ProcessCommunication** (см. `process_module/communication/process_communication.py`): `send_to_process` ↔ `send_message`, `broadcast` ↔ `broadcast_message`, `receive` ↔ `receive_message`. Каждое — алиас на алиас. Это «слой совместимости», но без чёткой стратегии вычистки.

### Tier 3 — улучшения качества

11. **Performance baseline** — отсутствует. `tests/performance/` нет. Нет ответа на «1000 send_message/sec не упрётся в Lock?», «10K logs/sec не уронит BatchBuffer?», «cross-process delta-рассылка StateStore масштабируется ли при 100 подписчиках?».

12. **CI matrix** (Linux/Windows/macOS × Python 3.12/3.13) — отсутствует. На macOS 15 SharedMemory тестов skip; на Windows — pickle edge-case с lambdas. Без CI это remains decoration, не гарантия.

13. **Sphinx/mkdocs** — нет автогенерации API-доки. На 21 модуле и 80K LOC — это **минус** для онбординга.

14. **Changelog** — нет. `__version__ = "2.0.0"` неизменно с 2026-04-25, хотя добавлены state_store + chain (минор-уровень).

---

## Сильные стороны (нет регрессий)

| Что | Где |
|---|---|
| **Регистр-ориентированная модель** (DSL: одно поле = тип + UI + маршрут) | `data_schema_module` + `RegistersManager` + `FieldRouting` |
| **CRM-паттерн** (DRY-фундамент для Logger/Router/Stats/Error) | `channel_routing_module` |
| **Per-process stop_event** | `ProcessRegistry` (ADR-PM-001) |
| **Bundle Contract** для pickle-safe передачи | `process_manager_module/launcher/bundle_contract.py` (ADR-PM-003) |
| **`BaseManager + ObservableMixin`** на каждом менеджере | `base_manager` (R-2) |
| **Dict at Boundary** соблюдается | везде, проверено |
| **Graceful shutdown без `sys.exit()`** (signal handler — только `stop_event.set()`) | `ProcessSpawner` (ADR-PM-006) |
| **Heartbeat monitoring** через `ProcessMonitor` | (ADR-PM-004) |
| **Server/client state store** с Protocol IRouter | `state_store_module` (ADR-SS-001) |
| **Standalone chain engine** | `chain_module` (не зависит от других модулей) |

---

## Приоритеты улучшений (актуализировано)

### Tier 1 — обязательно

1. **Синхронизировать документацию: 19 → 21 модуль.** Обновить `MODULE_CONTRACTS.md` (заголовок и сводная таблица), `DIAGRAMS.md` (граф зависимостей и слои), `STRUCTURE.md`, `MODULES_STATUS.md` — единая цифра. Срок: 1 день.

2. **Восстановить целостность корневого фасада.** Добавить в `__init__.py` экспорт ключевых символов из state_store / chain / sql / frontend. Допустимо — leaf-импорт: `from multiprocess_framework.modules.<X> import <Y>`. Сделать это общим правилом: «каждый production-модуль обязан иметь хотя бы один символ в корневом фасаде». Срок: 0.5 дня.

3. **Удалить алиас `ProcessStatus = ProcessStatusMonitor`** в `process_manager_module/core/process_status.py:111`. Найти все места, где импортируется именно `ProcessStatus` из этого пути (`grep`), мигрировать на `from multiprocess_framework.modules.process_manager_module import ProcessStatusMonitor`. Срок: 0.5 дня.

4. **Починить 2 failing-теста.** Либо `@pytest.mark.xfail(reason=...)` с TODO-ссылкой, либо реальный фикс (тесты доимиграционные, починить — час работы). Срок: 1-2 часа.

### Tier 2 — серьёзно повысит качество

5. **Унификация comm-API на ProcessModule.** Оставить только `send(msg) -> dict`. `send_message(target, msg)` — пометить deprecated, через 1-2 версии удалить. Срок: 1 день + 2 недели на миграцию приложений.

6. **CI matrix.** GitHub Actions на 3 платформах × 2 версии Python. Срок: 1 день настройки + работа над flaky-тестами.

7. **Performance baseline.** `tests/performance/` с pytest-benchmark на: 1000 send_message/sec, 10K logs/sec, 100 подписок в state_store, full bundle pickle/unpickle. Срок: 2-3 дня.

8. **Декомпозиция `data_schema_module`** на 3 под-пакета. ADR заранее. Срок: 1-2 недели.

9. **Sphinx или mkdocs.** Автогенерация API-доки из docstrings. Срок: 2-3 дня.

10. **Changelog.** `CHANGELOG.md` на корне, с привязкой версии к ADR. Срок: 0.5 дня + дисциплина.

### Tier 3 — perfectionism

11. **Линтер инвариантов** — pre-commit с проверкой R-1 (каноничные импорты), R-3 (Dict at Boundary), R-9 (нет `print`), R-11 (нет `sys.exit`).

12. **Decompose `frontend_module`.** Вынести в отдельный optional package `frontend_framework/` с зависимостью на `multiprocess_framework`.

13. **Унификация двойного dispatch** между `CommandManager` и `RouterManager.message_dispatcher` — оставить один источник истины.

14. **OpenTelemetry-adapter** в `RouterManager` для distributed tracing — задел на масштабирование на несколько хостов.

---

## Риски, не отражённые в оценке

1. **Прирост сложности `ProcessManagerProcess`.** Текущая декомпозиция (`_setup_console_manager`, `_setup_topology_manager`, `_setup_state_store`) — правильное направление, но при следующих 2-3 хуках понадобится явный механизм plugin-регистрации, иначе цепочка хуков превратится в anti-pattern «template method для всего».

2. **Связка `state_store` + `registers_module`.** Оба дают pub/sub изменений. Граница: `registers_module` — *именованные регистры* (pydantic-инстансы); `state_store_module` — *произвольное иерархическое дерево* (dict-tree). Сейчас граница только в документации. При несоблюдении — два источника истины. Стоит добавить ADR с явным разграничением.

3. **`ChannelRoutingManager` как базовый класс** — подразумевает наследование Logger/Router/Stats/Error. `RouterManager` уже отступает от паттерна (`buffer_strategy=None`, `channel_dispatcher = self._dispatcher`). При следующем CRM-наследнике (например, `MetricsExporterManager` для Prometheus) — стоит проверить, не нужен ли уже Strategy/Composition вместо наследования.

---

## Финальный комментарий

Фреймворк в **верхнем 15%** Python-проектов аналогичного размера. Архитектура продолжает усиливаться (state_store, chain — два сильных вертикальных решения). Документация — лучший актив, **но требует синхронизации** после Phase 2.

Главная управленческая боль: **drift между документацией и реальностью**. Когда `__init__.py`, `MODULE_CONTRACTS.md`, `DIAGRAMS.md`, `STRUCTURE.md` говорят «19 модулей», а в `modules/` — 21, это сигнал, что нужен **chore-таск перед каждым релизом**: «синхронизация публичных артефактов». Это решается чек-листом и парой строк в `tools/validate_all_modules.py`.

Главная инженерная сила: ничего не разваливается. Регистры держат UI ↔ backend, CRM держит наблюдаемость, Bundle Contract держит spawn'ы, per-process stop_event держит graceful shutdown. Каждый паттерн закрывает свою задачу. Это означает, что фреймворк готов к **росту приложения**, не к **росту самого фреймворка** — последнее требует CI и performance baseline.

**Рекомендация:** перед сборкой следующих фич прототипа (камера plugin, ML-pipeline) — пройти Tier-1 за 2-3 дня. Это снимет 80% долгов и оставит время на новые сборки.

---

## Приложение А — что подтвердил qex-индекс

Проведён сквозной semantic-search по 17 516 чанкам. Подтверждено:

- `ProcessStatus` (enum) реально один — в `base_manager/types/process_status.py`. Алиас `ProcessStatus = ProcessStatusMonitor` существует, но используется только как backward-compat name в одном файле.
- `ChannelRoutingManager` — реально базовый: `LoggerManager`, `RouterManager`, `StatsManager`, `ErrorManager` все наследуют его (через `ChannelRoutingManager` либо через `LoggerManager`).
- `RouterManager` действительно содержит **два** dispatcher'а: `channel_dispatcher` (alias на `_dispatcher` из CRM, для outgoing routing) и `message_dispatcher` (новый Dispatcher, для incoming). Оба независимы.
- `ProcessHandle` — chainable API существует (`srm.for_process(name).queue(type).send(msg)`). Pickle-safety обеспечена через `reinitialize_in_child()`.
- `state_store_module.IRouter` — Protocol, не наследник; RouterManager реализует duck-typed. Подтверждено в коде.
- `chain_module` действительно не зависит от других модулей фреймворка (только `base_manager` для `ChainThreadPool`).
