# Modules Overview — Из чего собирать приложение

**Назначение документа:** короткая карта 24 модулей фреймворка. Помогает разработчику и агенту понять, какой модуль закрывает какую задачу. Подробности — в `modules/<имя>/README.md`.

> **Границы и «где что»:** если сомневаешься, какой модуль отвечает за задачу (особенно config vs state vs registers, или два разных «EventBus») — сначала [`MODULES_RESPONSIBILITY_MAP.md`](MODULES_RESPONSIBILITY_MAP.md) (карта ответственности + матрица границ), потом сюда за деталями.

> **Формат:** для каждого модуля указано: роль, импорт с корня, ключевые классы, типичные применения, зависимости, ссылка на детали.

---

## Карта по слоям

```
Foundation         L1   base_manager  ◀── data_schema_module
                                         │
Routing primitives L2   dispatch_module  channel_routing_module
                                         │
Messaging          L3   message_module  router_module
                                         │
Observability      L4   logger_module  error_module  statistics_module
                                         │
Resources & Config L5   shared_resources_module  config_module  state_store_module
                                         │
Events (in-proc)   L6   event_module  ◀── generic typed pub/sub (факты)
                                         │
Command & Work     L7   command_module  actions_module  worker_module  chain_module
                                         │
Process            L8   process_module  console_module
                                         │
Orchestration      L9   process_manager_module  ◀── SystemLauncher (точка входа)
                                         │
Registries         L10  service_module  display_module
                                         │
Application kit    L11  registers_module
                                         │
UI (опционально)   L12  frontend_module (PySide6)
```

> **Storage вынесен из фреймворка:** `sql_module` переехал в `Services/sql` (Phase 4.1, ADR-121) — импорт `from Services.sql import SQLManager`. Во фреймворке его больше нет. Прикладные сервисы — см. [`Services/STATUS.md`](../../Services/STATUS.md).

---

## L1 — Foundation

### `base_manager` — фундамент всех менеджеров
**Импорт:** `from multiprocess_framework import BaseManager, ObservableMixin, BaseAdapter`
**Когда применять:** создаёшь свой менеджер. Любой менеджер фреймворка обязан наследовать `BaseManager + ObservableMixin`.
**Ключевое:** `BaseManager` (lifecycle: `initialize()/shutdown()`), `ObservableMixin` (прокси `_log_*`/`_record_*`/`_track_*`), `BaseAdapter` (адаптер для интеграции с процессом).
**Зависимости:** —
**Подробно:** [`modules/base_manager/README.md`](../modules/base_manager/README.md)

### `data_schema_module` — описание данных
**Импорт:** `from multiprocess_framework import SchemaBase, FieldMeta, FieldRouting, process`
**Когда применять:** описываешь регистр, конфиг процесса, конфиг менеджера. Это **единственный** способ декларировать структуру данных.
**Ключевое:** `SchemaBase` (Pydantic v2 + расширения), `FieldMeta` (UI-метаданные, валидация), `FieldRouting` (channel + process_targets), `SchemaRegistry`, `RegistersContainer`.
**Зависимости:** только Pydantic v2. **Не зависит от других модулей фреймворка** — leaf.
**Подробно:** [`modules/data_schema_module/README.md`](../modules/data_schema_module/README.md)

---

## L2 — Routing primitives

### `dispatch_module` — диспетчеризация ключ → handler
**Импорт:** `from multiprocess_framework import Dispatcher, DispatchStrategy, ScenarioBuilder`
**Когда применять:** нужно по ключу выбрать обработчик. 4 стратегии: `EXACT_MATCH`, `PATTERN_MATCH`, `FALLBACK_MATCH`, `CHAIN_MATCH` (сценарии).
**Ключевое:** `Dispatcher`, `BaseDispatcher` (lite, без observability), `ScenarioManager`, `ScenarioBuilder` (fluent API).
**Зависимости:** `base_manager`.
**Подробно:** [`modules/dispatch_module/README.md`](../modules/dispatch_module/README.md)

### `channel_routing_module` — паттерн CRM
**Импорт:** `from multiprocess_framework import ChannelRoutingManager`
**Когда применять:** свой менеджер с **каналами** (буферизацией, маршрутизацией в потоки/файлы/сокеты). Наследуешь `ChannelRoutingManager` — получаешь `ChannelRegistry`, `Dispatcher`, буферы (Direct/Batch/AsyncSender).
**Ключевое:** `ChannelRoutingManager`, `ChannelRegistry`, `IChannel`, буферные стратегии.
**Зависимости:** `base_manager`, `data_schema_module`, `dispatch_module`.
**Подробно:** [`modules/channel_routing_module/README.md`](../modules/channel_routing_module/README.md)

---

## L3 — Messaging

### `message_module` — value object для IPC
**Импорт:** `from multiprocess_framework import Message, MessageAdapter, MessageType`
**Когда применять:** создаёшь сообщение между процессами. **Используй `MessageAdapter`**, не `Message` напрямую — адаптер фиксирует sender один раз.
**Ключевое:** `Message` (`SchemaBase`, 9 типов), `MessageAdapter` (`adapter.command/log/system/broadcast/data/request/response/event`), `MessageType` (enum).
**Зависимости:** `data_schema_module`.
**Подробно:** [`modules/message_module/README.md`](../modules/message_module/README.md)

### `router_module` — маршрутизация сообщений между процессами
**Импорт:** `from multiprocess_framework import RouterManager`
**Когда применять:** в каждом процессе — один экземпляр. Внутри `ProcessModule` уже создан, обращаешься через `self.router`.
**Ключевое:** `RouterManager` (наследник CRM), `AsyncSender` (PriorityQueue + фоновый поток), `AsyncReceiver` (poll + callbacks), `IMessageChannel`.
**Зависимости:** `channel_routing_module`, `message_module`, `dispatch_module`.
**Подробно:** [`modules/router_module/README.md`](../modules/router_module/README.md)

---

## L4 — Observability

### `logger_module` — централизованное логирование
**Импорт:** `from multiprocess_framework import LoggerManager, get_logger`
**Когда применять:** в `ProcessModule` уже создан, не трогай напрямую — пиши `self._log_info("...")` через `ObservableMixin`.
**Ключевое:** `LoggerManager` (CRM-наследник), scope-based routing (SYSTEM/BUSINESS/PERFORMANCE/AUDIT/SECURITY), `BatchBuffer`, `FileChannel`/`ConsoleChannel`/`HttpChannel`.
**Зависимости:** `channel_routing_module`.
**Подробно:** [`modules/logger_module/README.md`](../modules/logger_module/README.md)

### `error_module` — управление ошибками
**Импорт:** `from multiprocess_framework import ErrorManager`
**Когда применять:** автоматически через `self._track_error(exc, context={...})`. Severity routing: `WARNING/ERROR/CRITICAL` → отдельные файлы.
**Ключевое:** `ErrorManager` (наследник `LoggerManager`), `log_exception()`, `_level_to_channel`.
**Зависимости:** `logger_module`.
**Подробно:** [`modules/error_module/README.md`](../modules/error_module/README.md)

### `statistics_module` — метрики
**Импорт:** `from multiprocess_framework import StatsManager`
**Когда применять:** автоматически через `self._record_metric(name, value)`/`self._record_timing(name, ms)`.
**Ключевое:** `StatsManager` (CRM-наследник), `AggregationWindow` (counter sum / gauge last / timing p95), `LogStatsChannel`, `FileStatsChannel`.
**Зависимости:** `channel_routing_module`.
**Подробно:** [`modules/statistics_module/README.md`](../modules/statistics_module/README.md)

---

## L5 — Resources & Config

### `shared_resources_module` — межпроцессные ресурсы
**Импорт:** `from multiprocess_framework import SharedResourcesManager, ProcessData, QueueRegistry, EventManager`
**Когда применять:** очереди, события, SharedMemory, ConfigStore — всё через SRM. **Pickle-safe** для Windows spawn.
**Ключевое:** `SharedResourcesManager` (фасад), `ProcessStateRegistry` (SoT для статуса), `ProcessHandle` (chainable: `srm.for_process("cam").queue("system").send(msg)`), `MemoryManager`, `EventManager`, `ConfigStore`.
**Зависимости:** `base_manager`.
**Подробно:** [`modules/shared_resources_module/README.md`](../modules/shared_resources_module/README.md)

### `config_module` — runtime-конфиги
**Импорт:** `from multiprocess_framework import ConfigManager`
**Когда применять:** управление конфигом на runtime: `config.get("database.host")`, `config.subscribe(callback)`, env-fallback, синхронизация через `ConfigStore` между процессами.
**Ключевое:** `ConfigManager`, `Config` (dot-notation + RLock + subscribe), `ConfigSection`.
**Зависимости:** `base_manager`, `data_schema_module`.
**Подробно:** [`modules/config_module/README.md`](../modules/config_module/README.md)

### `state_store_module` — реактивное дерево состояния
**Импорт:** `from multiprocess_framework.modules.state_store_module import StateStoreManager, StateProxy, TreeStore`
**Когда применять:** нужно глобальное состояние, видимое всем процессам — с подписками, дельтами и кэшированием. Server живёт в `ProcessManagerProcess`, клиенты — `StateProxy` в каждом рабочем процессе.

**Ключевое:**

- `StateStoreManager` — серверный фасад (TreeStore + SubscriptionManager + DeltaDispatcher). Регистрирует 7 IPC-команд: `state.set/merge/get/get_subtree/subscribe/unsubscribe/unsubscribe_all`.
- `TreeStore` — иерархическое дерево (`get/get_subtree/set/merge/delete`). Dot-path навигация. Glob-обход вынесен в общий `core/glob_walker.py`.
- `StateProxy` — клиентский прокси с локальным кэшем и подписками на glob-паттерны (`cameras.*.config.*`). **Фильтрует входящие дельты per-pattern** (ADR-SS-012) — callback видит только дельты своей подписки.
- `GuiStateProxy` — вариант StateProxy для PySide6 GUI (ленивый импорт PySide6).
- `Delta` — единица изменения (path, old/new value, source, timestamp).
- `SubscriptionManager` — публичные snapshot-методы `subscribers_snapshot()` / `subscriptions_for(subscriber)` для shutdown и DevTools (ADR-SS-013).
- `match_pattern` / `split_pattern` — публичные хелперы glob-матчинга (ADR-SS-004).
- Middleware pipeline: `ThrottleMiddleware`, `ValidationMiddleware` (поддерживает `tuple` types), `LoggingMiddleware`, `MetricsMiddleware`.
- `Selector` / `SelectorRegistry` — вычисляемые представления состояния.
- `StateInspector` — devtool: `inspect(pattern)`, `subscriptions()`, `history()`, `stats()`.
- `HealthMonitor` — watchdog по обновлениям путей.
- `PersistenceManager` — **доменно-нейтральный** (ADR-SS-011): принимает `file_mapping: dict[str, Path]` и опциональные `path_predicate` / `value_filter`; жёстко зашитых имён файлов больше нет.
- `RecipeEngine` — снимки (snapshot) и восстановление (restore) с поддержкой миграций через callback-и `migration_fn` / `migration_check_fn` (ADR-SS-003).
- `InMemoryRouter` — встроенный mock `IRouter` для unit-тестов (ADR-SS-010).

**Зависимости:** stdlib + `pyyaml` + `base_manager`; опционально `PySide6` (lazy). **Не зависит от RouterManager** — использует Protocol `IRouter` (ADR-SS-001).
**Подробно:** [`modules/state_store_module/README.md`](../modules/state_store_module/README.md)

---

## L6 — Events (in-proc)

### `event_module` — generic typed in-proc pub/sub
**Импорт:** `from multiprocess_framework.modules.event_module import EventBus, EventBusProtocol, Subscription`
**Когда применять:** нужно синхронно оповестить внутрипроцессных слушателей о **факте** («что произошло»: `TopologyReplaced`, `PluginConfigChanged`). Диспетчеризация по `type(event)` — подписчик на тип A получает только события типа A.
**Ключевое:** `EventBus` (`subscribe(Type, handler)` → `Subscription`; `publish(event)`), `EventBusProtocol`, `Subscription` (context-manager). Pure Python, шина не знает о доменных типах.
**Не путать:** это **in-proc факты**, а не cross-proc системные события (`EventManager` в `shared_resources_module`), не команды (`dispatch_module`) и не реактивное состояние (`state_store_module`). См. [`MODULES_RESPONSIBILITY_MAP.md`](MODULES_RESPONSIBILITY_MAP.md) §«Три оси событий».
**Зависимости:** stdlib (leaf).
**Подробно:** [`modules/event_module/README.md`](../modules/event_module/README.md)

---

## L7 — Command & Work

### `command_module` — команды (тонкий фасад над dispatch)
**Импорт:** `from multiprocess_framework import CommandManager`
**Когда применять:** регистрация обработчиков команд: `self.command_manager.register_command("name", handler)`. В `ProcessModule` уже создан.
**Ключевое:** `CommandManager` (с `BaseManager + ObservableMixin`), `BaseCommandManager` (lite). Синхронный by design — async-буфер уже выше через `RouterManager`.
**Зависимости:** `dispatch_module`, `base_manager`.
**Подробно:** [`modules/command_module/README.md`](../modules/command_module/README.md)

### `actions_module` — action-bus с undo/redo (для GUI)
**Импорт:** `from multiprocess_framework.modules.actions_module import Action, ActionBus, ActionBuilder`
**Когда применять:** нужна **отменяемая** мутация состояния из GUI: `ActionBus.execute(action)` с undo/redo-стеками, coalescing по `coalesce_key`, опциональным журналом. Carve-out из `frontend_module/actions/` (ADR-124).
**Ключевое:** `Action` (`SchemaBase`, `forward_patch`/`backward_patch`), `ActionBus` (undo/redo, coalescing, `IActionLogWriter`), `ActionBuilder` (фабрика; приложения наследуют), `SnapshotHistory`, `IRegistersManagerGui` (Protocol). Не требует PySide6; writer лога — в `Services/sql/action_log/`.
**Не путать:** `command_module` — это `имя → handler` (IPC-команды, без отката); `actions_module` — **действия с undo/redo** поверх регистров. Разные оси.
**Статус:** прод-undo в прототипе сейчас идёт через domain `CommandDispatcherOrchestrator` (не `ActionBus`); модуль сохраняется как переиспользуемый building-block. Подробнее — [`MODULES_RESPONSIBILITY_MAP.md`](MODULES_RESPONSIBILITY_MAP.md) §«command vs action».
**Зависимости:** `data_schema_module`.
**Подробно:** [`modules/actions_module/README.md`](../modules/actions_module/README.md)

### `worker_module` — потоки внутри процесса
**Импорт:** `from multiprocess_framework import WorkerManager, ThreadConfig, ThreadPriority`
**Когда применять:** создаёшь потоки в `ProcessModule` через `self.create_worker(name, fn, ThreadConfig(...), auto_start=True)`. Два режима: `LOOP` / `TASK`.
**Ключевое:** `WorkerManager` (lifecycle), `WorkerRegistry`, `WorkerLifecycle`, `ThreadConfig` (runtime), `ThreadWorkerConfig` (`SchemaBase`).
**Зависимости:** `base_manager`.
**Подробно:** [`modules/worker_module/README.md`](../modules/worker_module/README.md)

### `chain_module` — DAG/Chain execution engine

**Импорт:** `from multiprocess_framework.modules.chain_module import ChainRunnable, DagRunnable, ParallelChainRunnable, WorkerPoolDispatcher`
**Когда применять:** нужен pipeline обработки данных внутри процесса: последовательная цепочка шагов, DAG с ветвлениями, параллельные бандлы через пул потоков, или маршрутизация задач на worker-процессы.

**Ключевое:**

- `ChainRunnable` — последовательная цепочка. Принимает список `RunnableStep`, применяет по порядку.
- `DagRunnable` — DAG с ветвлениями 1→N и слияниями N→1 через именованные порты. Исполняет в топологическом порядке.
- `ParallelChainRunnable` — параллельные бандлы через `ChainThreadPool`. Бандлы — последовательно (barrier), шаги внутри бандла — параллельно.
- `ChainContext` — контекст выполнения (camera_id, seq_id, warnings, errors, timeout).
- `ChainResult` — результат цепочки (frame, detections, timing).
- `RunnableStep` — шаг: нода + операция + `on_error` политика.
- `ChainThreadPool` — `ThreadPoolExecutor` с timeout и graceful shutdown.
- Graph utilities: `topological_sort` (алгоритм Кана), `is_nonlinear_graph`, `detect_parallel_bundles`.
- Worker pool: `WorkerPoolDispatcher` (round-robin, backpressure, timeout), `WorkerTaskRequest`/`WorkerTaskResponse` (Dict at Boundary IPC-протокол).
- `IRemoteExecutable` — Protocol для cross-process шагов (`execute_remote` через `WorkerPoolDispatcher`); поддерживается всеми тремя исполнителями (ADR-CHN-006).
- `apply_on_error_policy` — единая обработка `on_error` (skip / fail_region / fail_camera) для всех исполнителей (ADR-CHN-006).
- `LatencyTracker(BaseManager, ObservableMixin)` — накапливает измерения, вычисляет p50/p95/p99 (numpy linear interpolation). Каждый `record()` пишется как timing метрика; `maybe_log()` публикует p50/p95/p99 snapshot в `StatsManager` (ADR-CHN-007).
- `WorkerPoolDispatcher(BaseManager, ObservableMixin)` — метрики `worker_pool.dispatched/timeouts/drops/late_responses/errors` (counter), `worker_pool.processing_time` (timing). Опциональные `logger`/`stats`/`errors`, обратно-совместимо (ADR-CHN-007).

**Зависимости:** `numpy`, `base_manager`, stdlib (`concurrent.futures`, `threading`). **Не зависит от других модулей фреймворка** — standalone (логи через `_log_*` ObservableMixin, не loguru напрямую).
**Подробно:** [`modules/chain_module/README.md`](../modules/chain_module/README.md)

---

## L8 — Process

### `process_module` — база дочернего процесса
**Импорт:** `from multiprocess_framework import ProcessModule`
**Когда применять:** **каждый твой процесс наследует `ProcessModule`**. Реализуешь `initialize()`, `run()`, `shutdown()`. Подсистемы (router/command/worker/logger/srm) уже сконструированы родителем.
**Ключевое:** `ProcessModule` (фасад), `ProcessLifecycle`, `ProcessManagers`, `ProcessCommunication`, `ProcessState`, `SystemThreads`. Два comm-API: `send_message(target, msg)` (`bool`) и `send(msg)` (dict со статусом).
**Зависимости:** `worker_module`, `router_module`, `logger_module`, `shared_resources_module`, `data_schema_module`.
**Подробно:** [`modules/process_module/README.md`](../modules/process_module/README.md)

### `console_module` — терминальный I/O
**Импорт:** `from multiprocess_framework import ConsoleManager`
**Когда применять:** нужен терминал у процесса. Три уровня: **Passive** (показ окна), **Active** (команды через `CommandManager`), **God Mode** (interactive=True — stdin → CommandManager → RouterManager).
**Ключевое:** `ConsoleManager`, `IPlatformConsole` (Windows/Unix), `ConsoleAdapter`, `ConsoleLogChannel`, `ConsoleRedirector`, `ConsoleProcessConfig` (готовый God Mode-процесс).
**Зависимости:** `base_manager`, `data_schema_module`, `logger_module`.
**Подробно:** [`modules/console_module/README.md`](../modules/console_module/README.md)

---

## L9 — Orchestration

### `process_manager_module` — оркестратор системы
**Импорт:** `from multiprocess_framework import SystemLauncher, ProcessManagerProcess, ProcessRegistry, ProcessMonitor, ProcessPriority`
**Когда применять:** **точка входа приложения**. Создаёшь `SystemLauncher`, добавляешь процессы, вызываешь `.run()`.
**Ключевое:**
- `SystemLauncher` — фасад (Dict at Boundary).
- `ProcessSpawner` — старт OS-процесса с оркестратором + signal handlers.
- `ProcessManagerProcess` — оркестратор-процесс (наследник `ProcessModule`), composite из `ProcessRegistry` + `ProcessMonitor` + `ProcessPriority`.
- `ProcessRegistry` — реестр (per-process `stop_event`, lifecycle).
- `ProcessMonitor` — heartbeat + state broadcast.
- Built-in commands: `process.list/start/stop/restart/status`, `system.shutdown/stats`.

**Зависимости:** `process_module`, `command_module`.
**Подробно:** [`modules/process_manager_module/README.md`](../modules/process_manager_module/README.md)

---

## L10 — Registries (реестры сущностей)

> Семейство «реестр именованных сущностей»: singleton + lifecycle (+ YAML-persist у display). Разные **сущности**, общий паттерн — см. [`MODULES_RESPONSIBILITY_MAP.md`](MODULES_RESPONSIBILITY_MAP.md) §«Семейство реестров».

### `service_module` — реестр long-running сервисов
**Импорт:** `from multiprocess_framework.modules.service_module import ServiceRegistry, register_service, IService, discover`
**Когда применять:** метаданные и жизненный цикл объектов с явным lifecycle (камеры, БД-подключения, auth-провайдеры). В отличие от `PluginRegistry` — без hot-reload, расширенный автомат `UNREGISTERED → READY → RUNNING → STOPPED → ERROR`.
**Ключевое:** `ServiceRegistry` (singleton), `IService` (Protocol), `@register_service`, `scanner.discover(*dirs)` → `DiscoveryResult`, `ServiceEntry`, `ServiceLifecycle`. Не знает о реализациях из `Services/` — инстанцирование на application-слое.
**Зависимости:** `base_manager` (+ stdlib). ADR-129.
**Подробно:** [`modules/service_module/README.md`](../modules/service_module/README.md)

### `display_module` — реестр SHM-каналов отображения кадров
**Импорт:** `from multiprocess_framework.modules.display_module import DisplayRegistry, DisplayEntry`
**Когда применять:** декларативно объявить именованные SHM-каналы для кадров; при старте `SharedResourcesManager` читает blueprint и создаёт SHM-сегменты. Модуль generic — не знает о numpy/vision-семантике (shape/dtype вычисляет prototype-слой).
**Ключевое:** `DisplayRegistry` (singleton, thread-safe, YAML persist/load), `DisplayEntry` (dataclass), `IDisplayRegistry`/`IDisplayChannel` (Protocol). ADR-130.
**Зависимости:** stdlib + `pyyaml`.
**Подробно:** [`modules/display_module/README.md`](../modules/display_module/README.md)

> **Storage (`sql_module`)** вынесен в `Services/sql` (Phase 4.1, ADR-121): `from Services.sql import SQLManager, SQLManagerConfig` — DDL из `SchemaBase`, `QuerySet[T]`, `UnitOfWork`, `TableExporter`. Детали — [`Services/sql/README.md`](../../Services/sql/README.md).

---

## L11 — Application kit

### `registers_module` — runtime регистров
**Импорт:** `from multiprocess_framework import RegistersManager`
**Когда применять:** работа с **живыми экземплярами** регистров (в отличие от `data_schema_module` — описание/чертёж). Pub/sub изменений, `set_field_value()` с fan-out, `build_routing_map()`, `send_register_message()`.
**Ключевое:** `RegistersManager` (композирует `RegistersContainer`), `resolve_dispatch_targets()`, `connection_map`, observers.
**Зависимости:** `data_schema_module`.
**Подробно:** [`modules/registers_module/README.md`](../modules/registers_module/README.md)

---

## L12 — UI (опционально)

### `frontend_module` — PySide6-виджеты с привязкой к регистрам
**Импорт:** `from multiprocess_framework.modules.frontend_module import FrontendManager`
**Когда применять:** GUI-процесс приложения. Виджет → `FrontendRegistersBridge` → регистр → `RouterManager`. Конфиг рядом с виджетом (`config.py` в каждой папке `components/<name>/`).
**Ключевое:** `FrontendManager` (`BaseManager`), `FrontendRegistersBridge`, координаторы, `FrontendAppContext`, библиотека готовых компонентов (numeric, slider, spinbox, compound, table…).
**Зависимости:** `process_module`, `router_module`, `data_schema_module`. PySide6.
**Подробно:** [`modules/frontend_module/README.md`](../modules/frontend_module/README.md), [`modules/frontend_module/WIDGET_COOKBOOK.md`](../modules/frontend_module/WIDGET_COOKBOOK.md)

---

## Типичные сборки приложений

### A. Минимальное многопроцессное приложение
`SystemLauncher` + N × `ProcessModule` (свои наследники) + `RouterManager` + `LoggerManager`. Этого достаточно для CLI-демона с IPC.

**Используем:** `process_manager_module`, `process_module`, `router_module`, `message_module`, `logger_module`, `worker_module`, `shared_resources_module`, `data_schema_module`, `base_manager`.

### B. Приложение с GUI и регистрами (как Inspector_bottles v3)
A + `frontend_module` + `registers_module` + `config_module` + `error_module` + `statistics_module` + `console_module`.

**Связка:** прикладные регистры (наследники `SchemaBase` с `FieldRouting`) живут в `registers_module`. Виджеты `frontend_module` подписываются на регистр; изменения uplinkятся через `RouterManager` в backend-процессы. Конфиги — `ConfigManager` с подписками.

### C. Приложение с БД
A + `sql_module` (+ опционально B). SQL-воркеры в отдельном процессе, команды через `Dict at Boundary`.

### D. Hardware-приложение (камера, контроллеры)
A + B + воркер с захватом кадров (LOOP-режим в `worker_module`); кадры отправляются через `Message(type=DATA)` в процесс детектора.

---

## Куда идти дальше

| Цель | Документ |
|------|----------|
| Понять архитектуру в целом | [`SPEC.md`](../SPEC.md) |
| Найти точный API модуля | `modules/<X>/README.md` |
| Посмотреть контракт интерфейса | `modules/<X>/interfaces.py` |
| Узнать «почему так» (ADR) | глобальный [`DECISIONS.md`](../DECISIONS.md) + локальные `modules/<X>/DECISIONS.md` |
| Цепочка взаимодействия | [`INTERACTION_FLOWS.md`](INTERACTION_FLOWS.md) |
| Императивные правила | [`DESIGN_RULES.md`](DESIGN_RULES.md) |
| Термины | [`GLOSSARY.md`](GLOSSARY.md) |
| Контракты по каждому модулю | [`MODULE_CONTRACTS.md`](MODULE_CONTRACTS.md) |
