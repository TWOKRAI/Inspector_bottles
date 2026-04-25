# Module Contracts — Контракты модулей

**Назначение:** для каждого из 19 модулей указано: цель, публичный контракт (`interfaces.py` + ключевые классы), обязательные инварианты, входы/выходы, зависимости. Документ — параллельная сетка к [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md): тот навигатор «когда применять», этот — «что обязано быть».

> **Формат записи модуля:**
> - **Цель** — одно предложение
> - **Контракт** — основные классы / Protocol / ABC из `interfaces.py`
> - **Инварианты** — обязательные требования к реализации
> - **Зависимости** — другие модули фреймворка
> - **Тестов** — приблизительно

---

## L1 — Foundation

### `base_manager`

**Цель:** Жизненный цикл и наблюдаемость для всех менеджеров фреймворка.

**Контракт:**
- `BaseManager(ABC)` — `initialize() -> bool`, `shutdown() -> bool`, `attach_adapter(name, adapter)`, `get_adapter(name)`, `detach_adapter(name)`, `get_debug_info() -> dict`.
- `ObservableMixin` — приватные прокси `_log_*`, `_record_metric`, `_record_timing`, `_track_error`. Публичные `log_*`/`record_*`/`track_*` — только при `auto_proxy=True`.
- `BaseAdapter(ABC)` — `setup(manager)`, `teardown()`.
- `IBaseManager`, `IObservableMixin`, `IBaseAdapter` — `Protocol`.

**Инварианты:**
1. Любой менеджер фреймворка наследует `BaseManager + ObservableMixin`.
2. `_log_*` после unpickle возвращает `None` без исключения, пока managers-реестр не восстановлен.
3. Адаптеры подключаются через `attach_adapter()`, **не** через `setattr`.

**Зависимости:** —
**Тестов:** ~30+

---

### `data_schema_module`

**Цель:** Декларативное описание данных через Pydantic v2 + расширения. Единый источник истины для регистров и конфигов.

**Контракт:**
- `SchemaBase(BaseModel)` — базовый класс; миксин `SchemaMixin` (`build()` → `(name, model_dump())` для Dict at Boundary).
- `FieldMeta` — дескриптор поля: `description`, `min_value/max_value`, `unit`, `routing`, `access_level`, `ui_*` (placeholder, помощь и т.п.).
- `FieldRouting` — `channel: str`, `process_targets: list[str]`, опциональный `transform`.
- `RegisterDispatchMeta` — цели доставки на уровне всего регистра.
- `SchemaRegistry` — реестр зарегистрированных схем без Singleton.
- `RegistersContainer` — контейнер экземпляров с `model_dump_all()` / `model_validate_all()`.
- `DataConverter`, `FileStorage` — сериализация (dict / JSON / YAML).
- `process` (декоратор/хелпер) — нормализация конфига процесса.
- `register_schema` (декоратор) — регистрация в `SchemaRegistry`.

**Инварианты:**
1. **Не зависит** от других модулей фреймворка — leaf в графе.
2. Доступ к `model_fields` — только через `type(instance).model_fields` (Pydantic v2.11+).
3. `FieldRouting.channel` обязателен; `process_targets` — опционально.
4. Все производные структуры (диффы, snapshot) — pickle-safe (plain dict).

**Зависимости:** —
**Тестов:** ~80+

---

## L2 — Routing primitives

### `dispatch_module`

**Цель:** Сопоставление dict-сообщения с обработчиком по ключу/стратегии.

**Контракт:**
- `IDispatcher` — `register_handler(key, handler, strategy?, metadata?)`, `dispatch(payload, key=None)`, `get_handler(key)`, `unregister_handler(key)`.
- `Dispatcher` — реализация с `BaseManager + ObservableMixin`, поддержка 4 стратегий через `strategies/`, `ScenarioManager` (CRUD + `dispatch_scenario`), сценарии через `ScenarioBuilder` (fluent).
- `BaseDispatcher` — облегчённый, только `EXACT_MATCH`, без observability.
- `DispatchStrategy` — enum (`EXACT_MATCH`, `PATTERN_MATCH`, `FALLBACK_MATCH`, `CHAIN_MATCH`).
- `HandlerInfo`, `Scenario` — value objects.

**Инварианты:**
1. `EXACT_MATCH` — O(1) lookup по ключу.
2. Сценарий = последовательность handler'ов; обрыв при ошибке.
3. Регистрация и dispatch — потокобезопасны.

**Зависимости:** `base_manager`.
**Тестов:** ~56

---

### `channel_routing_module`

**Цель:** Базовый класс канальных менеджеров (CRM-паттерн). Любой менеджер с *каналами* (вывод в файлы/потоки/сокеты) наследует `ChannelRoutingManager`.

**Контракт:**
- `ChannelRoutingManager(BaseManager, ObservableMixin)` — фасад из четырёх частей: `ChannelRegistry`, `Dispatcher`, `IBufferStrategy`, `normalize_config()`.
- `IChannel(ABC)` — `send(record) -> bool`, `flush()`, `close()`.
- `ChannelRegistry` — `register/get/unregister/list_channels` (потокобезопасно).
- `IBufferStrategy(ABC)` — `Direct` (sync) / `Batch` (size+interval) / `AsyncSender` (PriorityQueue + thread).
- `ChannelRoutingConfig(SchemaBase)` — конфиг с каналами, scopes, mappings.

**Инварианты:**
1. Все наследники CRM (`LoggerManager`, `RouterManager`, `StatsManager`, `ErrorManager`) переиспользуют `_channel_registry` и `_dispatcher`.
2. Конфиг нормализуется через `normalize_config()`: принимает `dict` / `None` / `SchemaBase`.
3. Замена/удаление канала — атомарно под `RLock`.

**Зависимости:** `base_manager`, `data_schema_module`, `dispatch_module`.
**Тестов:** ~58

---

## L3 — Messaging

### `message_module`

**Цель:** Value object для IPC-сообщения и фабрика-адаптер.

**Контракт:**
- `IMessage(Protocol)` — поля: `id`, `type`, `sender`, `targets`, `channel`, `priority`, `ts`, `data`.
- `Message(SchemaBase)` — реализация с `model_dump()`/`from_dict()`, fluent API: `set_priority`, `set_targets`, `set_channel`.
- `MessageType(str, Enum)` — `COMMAND/LOG/SYSTEM/BROADCAST/DATA/REQUEST/RESPONSE/EVENT/GENERAL`.
- `MessageAdapter(sender)` — `command(targets, command, args, …)`, `log(level, msg, …)`, `system(targets, action, …)`, `broadcast(content, …)`, `data(targets, data_type, data, …)`, `request(targets, request_type, …)`, `response(targets, request_id, result, …)`, `event(event_type, …)`.
- `IMessageFactory(Protocol)` — для тестовых дублёров.
- Опциональные строгие схемы: `CommandMessageSchema`, `LogMessageSchema` (`extra='forbid'`).

**Инварианты:**
1. **Dict at Boundary:** только `msg.to_dict()` пересекает границу процесса.
2. `MessageAdapter.<type>()` — рекомендованный способ. Прямое создание `Message(...)` — допустимо, но без фиксации `sender`.
3. `request_id` (correlation_id) обязателен для пары REQUEST/RESPONSE.

**Зависимости:** `data_schema_module`.
**Тестов:** ~50+

---

### `router_module`

**Цель:** Маршрутизация сообщений между процессами через каналы (Queue / Socket / HTTP).

**Контракт:**
- `IMessageChannel(IChannel)` — `send(msg_dict) -> bool`, `receive() -> Optional[dict]`.
- `RouterManager(ChannelRoutingManager)` — фасад: `send(msg)`, `receive()`, `register_channel(name, channel)`, `register_message_handler(key, handler)`, `register_middleware(direction, fn)`.
- `AsyncSender` — outgoing pipeline: PriorityQueue + thread.
- `AsyncReceiver` — poll thread + fire-and-forget callbacks.
- `RouterAdapter` — обёртка для `ProcessModule` (фиксированный sender, `send_to_channel`).
- `RouterSchemaAdapter` — `FieldRouting` → карта каналов для регистрации.

**Инварианты:**
1. Один `RouterManager` на процесс.
2. `channel_dispatcher` (`= CRM._dispatcher`) маршрутизирует исходящие; `message_dispatcher` — входящие.
3. Handlers возвращают **имя канала** (а не результат записи).
4. `_stats` — потокобезопасно (`threading.Lock`).

**Зависимости:** `channel_routing_module`, `message_module`, `dispatch_module`.
**Тестов:** ~80+

---

## L4 — Observability

### `logger_module`

**Цель:** Логирование со scope-based маршрутизацией и батчингом.

**Контракт:**
- `ILogChannel(IChannel)`.
- `LoggerManager(ChannelRoutingManager)` — `info/debug/warning/error/critical/<scope>` + `should_log(level, scope)`.
- `LoggerManagerConfig(SchemaBase)` — каналы, scopes, modules.
- `LogScope(str, Enum)` — `SYSTEM/BUSINESS/PERFORMANCE/AUDIT/SECURITY/DEBUG`.
- `LogLevel(str, Enum)` — `DEBUG/INFO/WARNING/ERROR/CRITICAL`.
- `LogRecord` — dataclass.
- `LoggerAdapter` — обёртка для multiprocess.
- `get_logger(name)` — фабрика.
- Каналы: `FileChannel`, `ConsoleChannel`, `HttpChannel`.

**Инварианты:**
1. `BatchBuffer` сбрасывает по size *или* interval.
2. `LogRecord` — отдельный тип в `core/log_types.py` (не вложен в config).
3. `log_enums.py` лежит на уровне модуля (`logger_module/log_enums.py`), **не** внутри `core/` — иначе цикл импорта между `configs` и `core`.

**Зависимости:** `channel_routing_module`.
**Тестов:** ~40+

---

### `error_module`

**Цель:** Severity-based маршрутизация ошибок поверх `LoggerManager`.

**Контракт:**
- `ErrorManager(LoggerManager)` — `_level_to_channel: dict[LogLevel, str]`, override `log()`, `log_exception(exc, context=None)`, `track_error(exc, context=None)` (для `ObservableMixin`).
- `ErrorManagerConfig(SchemaBase)` — пути для `critical.log` / `errors.log` / `warnings.log`.
- `expand_error_manager_config()` — конвертирует `ErrorManagerConfig` → `LoggerManagerConfig`.

**Инварианты:**
1. Наследник `LoggerManager` (не композиция, не слияние).
2. `_level_to_channel = {}` инициализируется **до** `super().__init__()` — защита от `AttributeError`.
3. `WARNING+` идёт по severity routing; `DEBUG/INFO` — fallback на scope-based parent.

**Зависимости:** `logger_module`.
**Тестов:** ~25+

---

### `statistics_module`

**Цель:** Метрики и агрегация — counter / gauge / timing / histogram. Прямой наследник CRM.

**Контракт:**
- `IStatsManager` — `record_counter(name, value=1, tags=None)`, `record_gauge(name, value, tags)`, `record_timing(name, ms, tags)`, `record_histogram(name, value, tags)`, `get_metric(name)`, `get_all_metrics()`.
- `StatsManager(ChannelRoutingManager)` — dual-layer: live-dict + `AggregationWindow`.
- `AggregationWindow(IBufferStrategy)` — counter sum, gauge last, timing p95/p99.
- `LogStatsChannel(IChannel)` → `LoggerManager.performance()`.
- `FileStatsChannel(IChannel)` → JSON/CSV.
- `StatsAdapter(BaseAdapter)` → 5 команд CommandManager.
- `MetricRecord` — dataclass.

**Инварианты:**
1. Sentinel-паттерн: `enqueue` один раз → `flush` во все каналы (без N-кратного счёта).
2. `get_metric` читает из `_metrics` (live), не из буфера.

**Зависимости:** `channel_routing_module`.
**Тестов:** ~40+

---

## L5 — Resources & Config

### `shared_resources_module`

**Цель:** Pickle-safe реестр межпроцессных ресурсов (Queue / Event / SharedMemory) + `ConfigStore` + `ProcessStateRegistry`.

**Контракт:**
- `SharedResourcesManager` — фасад: `register_process(name, config)`, `for_process(name) -> ProcessHandle`, `reinitialize_in_child()`.
- `ProcessHandle` — chainable: `.queue("name").send(msg) | .event("name").set() | .memory("name").write(data)`.
- `ProcessStateRegistry` — SoT для статуса/очередей/событий процессов.
- `ProcessData` — dataclass: `status`, `queues`, `events`, `metadata`.
- `QueueRegistry` — делегирует в PSR (не кеширует).
- `EventManager` — системные события + подписки + router-интеграция.
- `MemoryManager` — `SharedMemory` lifecycle (owner create/unlink, consumer open/close).
- `MemoryAccessStatus(Enum)` — `OK / NOT_FOUND / PERMISSION / PLATFORM_LIMIT`.
- `ConfigStore` — pickle-safe dict для статической конфигурации.
- `EventType(Enum)`.

**Инварианты:**
1. **Pickle-safe:** все объекты передаются в дочерний процесс через `Process(args=...)`.
2. После unpickle — `srm.reinitialize_in_child()` восстанавливает `EventManager._event_queue` и `MemoryManager.handles`.
3. `ConfigStore = dict`, **не** Pydantic-объект.
4. `ProcessStateRegistry` — единственный источник истины для статуса процесса (другие источники запрещены).

**Зависимости:** `base_manager`.
**Тестов:** ~50+ (15 пропущены на macOS)

---

### `config_module`

**Цель:** Runtime-доступ к конфигам с подписками на изменения и cross-process синхронизацией через `ConfigStore`.

**Контракт:**
- `IConfigManager` — `create_config`, `get_config`, `remove_config`, `sync_config`, `load_config_from_storage`, `subscribe`.
- `ConfigManager(BaseManager, ObservableMixin)` — коллекция `Dict[str, Config]`.
- `Config` — dict + RLock + dot-notation (`config.get("a.b.c")`) + подписки + env-fallback.
- `ConfigSection` — view на подсекцию.
- `ConfigManagerConfig(SchemaBase)` — собственный конфиг.

**Инварианты:**
1. **Тонкая обёртка над `data_schema_module`** (ADR-023). Валидация и сериализация делегируются туда.
2. `Config` не делает I/O — загрузка/сохранение только через `ConfigStore` или внешние утилиты.
3. Env-fallback: `{env_prefix}_{KEY}`, опционально.
4. Cross-process: `sync_config()` → `ConfigStore` (dict at boundary), `load_config_from_storage()` ← `ConfigStore`.

**Зависимости:** `base_manager`, `data_schema_module`.
**Тестов:** 49

---

## L6 — Command & Work

### `command_module`

**Цель:** Тонкий фасад над `dispatch_module` с семантикой «команды».

**Контракт:**
- `ICommandManager` — `register_command(name, handler, metadata=None)`, `handle_command(msg) -> Any`, `get_commands()`, `get_command_info(name)`, `get_commands_by_tag(tag)`, `overwrite_command`, `update_command_metadata`, `update_command_tags`.
- `CommandManager(BaseManager, ObservableMixin)` — внутренний `Dispatcher` для `msg["command"]` → handler.
- `BaseCommandManager` — lite, только `EXACT_MATCH`, без `ObservableMixin`.
- `CommandAdapter(BaseAdapter)` — `execute_via_message()`.
- `CommandManagerConfig(SchemaBase)` — плоская схема для UI.

**Инварианты:**
1. **Синхронный by design** (ADR-172): async-буфер уже выше через `RouterManager`.
2. CommandManager маршрутизирует **к функциям**, CRM — **в каналы**. Не путать.
3. Тяжёлая работа в handler'е → выносится в worker thread, не в async command.

**Зависимости:** `dispatch_module`, `base_manager`.
**Тестов:** 34

---

### `worker_module`

**Цель:** Lifecycle потоков-воркеров внутри процесса.

**Контракт:**
- `IWorkerManager` — `create_worker(name, fn, config, auto_start=False)`, `start/stop/restart/pause/resume`, `get_status(name)`.
- `WorkerManager(BaseManager, ObservableMixin)` — фасад: `WorkerRegistry` (storage) + `WorkerLifecycle` (create/start/stop, auto-restart).
- `WorkerInfo` — `name, thread, config, status, started_at, restarts`.
- `ThreadConfig` — runtime: `priority: ThreadPriority`, `worker_type: WorkerType`, `execution_mode: ExecutionMode`, `auto_restart: bool`, `max_restarts: int`.
- `ThreadWorkerConfig(SchemaBase)` — декларативный (для конфига процесса).
- `WorkerStatus(Enum)` — `READY/RUNNING/PAUSED/STOPPED/COMPLETED/ERROR`.
- `WorkerType(Enum)` — `APPLICATION/SYSTEM/BACKGROUND`.
- `ExecutionMode(Enum)` — `LOOP/TASK`.
- `ThreadPriority(Enum)` — `LOW/NORMAL/HIGH`.
- `WorkerAdapter(BaseAdapter)` — обёртка для `ProcessModule`.
- `WorkerSchemaAdapter` — извлечение `ThreadConfig` из `SchemaBase`-конфигов.

**Инварианты:**
1. **Не зависит** от `dispatch_module`: WorkerManager — lifecycle, не маршрутизация (ADR-159).
2. Каждый воркер получает `(stop_event, pause_event)` и обязан проверять оба в цикле.
3. `LOOP` — финальный статус `STOPPED`; `TASK` — финальный статус `COMPLETED`.

**Зависимости:** `base_manager`.
**Тестов:** 49

---

## L7 — Process

### `process_module`

**Цель:** База дочернего процесса. Сборка всех подсистем в один класс.

**Контракт:**
- `IProcessModule(Protocol)` — `initialize() -> bool`, `run() -> None`, `shutdown() -> bool`, `should_stop() -> bool`, `send_message(target, msg) -> bool`, `send(msg) -> dict`, `create_worker(name, fn, config, auto_start=False)`, свойства `router`, `command_manager`, `worker_manager`, `logger_manager`, `error_manager`, `stats_manager`, `console_adapter`, `msg`, `process_data`.
- `ISharedResources(Protocol)` — DI вместо жёсткой привязки к `SharedResourcesManager`.
- `ProcessModule(BaseManager, ObservableMixin)` — фасад. Делегирует:
  - `ProcessLifecycle` — `initialize/shutdown`, `_init_configuration`, `_init_queues`.
  - `ProcessManagers` — pipeline создания подменеджеров.
  - `ProcessCommunication` — `send_message`, `send`, `broadcast`, `receive_message`.
  - `ProcessState` — регистрация и обновление в `ProcessStateRegistry`.
  - `SystemThreads` — системные потоки (например `message_processor`).
- `ProcessStatus(Enum)` — `INITIALIZING/READY/RUNNING/STOPPING/STOPPED/ERROR/CRASHED/UNRESPONSIVE/FAILED`.
- `ProcessLaunchConfig(SchemaBase)` — конфиг запуска (используется `process()` хелпером).

**Инварианты:**
1. **Два comm-API** (ADR-163): `send_message` (`bool`) — простой; `send` (`dict` со статусом) — расширенный.
2. **Воркеры из конфига** — через `importlib.import_module` (ADR-167), не через прямые импорты.
3. `should_stop()` читает `stop_event` — проверять в каждой итерации `run()`.
4. Конфиг и очереди инициализируются в `ProcessLifecycle`, вызов через `ProcessModule._init_*` (делегаты, ADR-166a).

**Зависимости:** `worker_module`, `router_module`, `logger_module`, `shared_resources_module`, `data_schema_module`.
**Тестов:** ~60+

---

### `console_module`

**Цель:** Терминальный I/O процесса (три уровня: passive / active / God Mode).

**Контракт:**
- `IConsoleManager` — `show/hide/write`, `enable_input(callback)/disable_input()`, `setup_redirect(enabled)`, `create_console/close_console/list_consoles`.
- `ConsoleManager(BaseManager, ObservableMixin)`.
- `IPlatformConsole(ABC)` — `show/hide/set_title/write/close`.
  - `WindowsConsole` (Win32: `SetConsoleTitle`, `AllocConsole`, `ShowWindow`).
  - `UnixConsole` (ANSI + `sys.stdin`).
- `create_platform_console()` — фабрика по `sys.platform`.
- `ConsoleAdapter(BaseAdapter)` — связывает с `LoggerManager` (`ConsoleLogChannel`) и `CommandManager` (input loop).
- `ConsoleLogChannel(IChannel)` — канал лога.
- `ConsoleRedirector` — перехват `sys.stdout`/`sys.stderr` (прямой вызов `ConsoleManager.write()`, без Queue).
- `ConsoleConfig(SchemaBase)` — `enabled, interactive, title, redirect_stdout`.
- `ConsoleProcessConfig(ProcessLaunchConfig)` — God Mode standalone-процесс.
- Встроенные команды: `RegisterCommandHandler` (`reg list/get/set/info/help`), `SystemCommandHandler` (`help/status/ps/stats`).

**Инварианты:**
1. Один `ConsoleManager` для всех трёх уровней — не три класса (ADR-CM-001).
2. God Mode — конфигурация (`ConsoleProcessConfig`), не отдельный класс (ADR-CM-002).
3. `ConsoleLogChannel` — в `console_module`, не в `logger_module` (ADR-CM-003).
4. Платформенная логика — в `IPlatformConsole`, фабрика выбирает реализацию (ADR-CM-004).

**Зависимости:** `base_manager`, `data_schema_module`, `logger_module`.
**Тестов:** ~40+

---

## L8 — Orchestration

### `process_manager_module`

**Цель:** Запуск, мониторинг, управление, завершение всех процессов системы.

**Контракт:**
- `ISystemLauncher` — `add_process(name, dict)`, `run()`, `stop()`, `get_status() -> dict`.
- `SystemLauncher` — фасад. Принимает `processes: list[(name, proc_dict)]` (Dict at Boundary).
- `IProcessRegistry` — `create_and_register/start_one/stop_one/stop_all/restart_one/remove_process/list_processes`.
- `ProcessRegistry` — `_stop_events: dict[name, Event]` (per-process!).
- `IProcessManagerProcess` — `monitor`, `priority`, `status` контракты.
- `ProcessManagerProcess(ProcessModule)` — оркестратор-процесс (composite из ProcessRegistry + ProcessMonitor + ProcessPriority + ProcessStatus + EventManager).
- `ProcessSpawner` — `launch_orchestrator()` (создаёт OS Process + signal handlers), `wait()`, `stop(timeout=5)`.
- `ProcessMonitor` — heartbeat thread + state polling + broadcast.
- `ProcessPriority(Enum)` — `LOW/NORMAL/HIGH/URGENT`. `apply()` ставит OS-приоритет.
- `ProcessStatus` — отчётность (`get_process_status/get_all_status/get_stats`).
- `ProcessSchemaAdapter` — `SchemaBase` → `proc_dict` (Dict at Boundary).
- `bundle_contract.py` — `build_bundle/validate_bundle` для pickle-safe передачи.
- `run_process_function` — top-level runner для дочернего процесса (pickle-safe).

**Инварианты:**
1. **Per-process stop events** (ADR-PM-001): остановка одного не затрагивает других.
2. **Минималистичный ProcessSpawner** (ADR-PM-002): только SRM + signal, без ConfigManager/LoggerManager/ErrorManager.
3. **Bundle Contract** (ADR-PM-003): pickle-safe формализованный dict для дочернего процесса.
4. **Heartbeat monitoring** (ADR-PM-004): `process.is_alive()` для обнаружения crashed.
5. **Signal handler** только устанавливает `stop_event`, **не вызывает `sys.exit()`** (ADR-PM-006).

**Зависимости:** `process_module`, `command_module`.
**Тестов:** ~80+

---

## L9 — Storage

### `sql_module`

**Цель:** SQL-инструментарий поверх `SchemaBase` (DDL, типизированные репозитории, QuerySet, UoW, экспорт).

**Контракт:**
- `SQLManager(BaseManager, ObservableMixin)` — `execute(sql, params)`, `query(sql, params)`, `create_tables(schema_classes, dialect)`, `objects(schema_class) -> QuerySet`, `get_repository(schema_class) -> IRepository`, `uow()/uow_async()`, `execute_command(cmd_dict) -> dict`.
- `ISyncEngineAdapter`/`IAsyncEngineAdapter` — Strategy pattern.
- `ISchemaMapper` — `entity_to_row/row_to_entity`.
- `IRepository[T, ID]` / `GenericRepository` — типизированный CRUD.
- `IUnitOfWork` / `IAsyncUnitOfWork` — транзакции.
- `QuerySet[T]` — Django-style immutable builder.
- `DDLBuilder` — генерация DDL для SQLite/PostgreSQL/MySQL.
- `SchemaBaseMapper` — реализация ISchemaMapper.
- `SQLMeta` — ClassVar (table_name, indexes, unique_together).
- `TableExporter` — TXT/CSV/XLSX.
- `DBQueryCommand`, `DBExecuteCommand`, `DBInsertCommand` — typed dict commands.

**Инварианты:**
1. **Dict at Boundary**: `execute/query/execute_command` принимают/возвращают `dict`.
2. `QuerySet` — immutable, без побочных эффектов.
3. **Fork-safety:** при `INSPECTOR_MULTIPROCESS=1` или `config.fork_safe=True` адаптер использует `NullPool`.
4. Async-адаптер создаётся лениво при первом вызове.

**Зависимости:** `base_manager`, `data_schema_module`.
**Тестов:** ~70+

---

## L10 — Application kit

### `registers_module`

**Цель:** Runtime вокруг **именованных экземпляров** регистров.

**Контракт:**
- `IRegistersManager` — `add_register/remove_register`, `set_field_value(register, field, value)`, `get_field_value/get_field_metadata`, `subscribe_field/unsubscribe_field`, `subscribe_all`, `build_routing_map() -> Dict[(reg, field), {channel, ...}]`, `send_register_message(register, field, value, sender)`.
- `RegistersManager(BaseManager, ObservableMixin)` — композирует `RegistersContainer` (хранение из `data_schema_module`).
- `core/dispatch.py::resolve_dispatch_targets()` — выбор целей доставки.
- `build_routing_map` / `build_connection_map_from_registers` — построение карт маршрутизации.

**Инварианты:**
1. `RegistersManager` **не** дублирует `RegistersContainer` — композирует (ADR-RM-001).
2. Все доступы к `model_fields` — через класс, не через инстанс (Pydantic v2.11+).
3. `set_field_value` валидирует через `data_schema_module`, fan-out — в callback `send_register_message`.

**Зависимости:** `data_schema_module`.
**Тестов:** ~30+

---

## L11 — UI (опционально)

### `frontend_module`

**Цель:** PyQt5-фреймворк виджетов с привязкой к регистрам.

**Контракт:**
- `IFrontendManager` — управление окнами/виджетами, привязка к `RegistersManager`.
- `FrontendManager(BaseManager, ObservableMixin)` — единая точка входа в UI-подсистему.
- `FrontendRegistersBridge` — связь виджет ↔ регистр (subscribe регистр → update UI; user input → `set_field_value`).
- `FrontendAppContext` — явный контекст вкладок без слияния слоёв (ADR-084).
- `coordinators/` — слой между виджетом, Presenter и managers (ADR-090).
- Компоненты: `numeric`, `slider`, `spinbox`, `compound`, `checkbox`, `tables`, `table_widgets`, и т.д. — каждая папка с `config.py` (ADR-044).
- `WindowConfig`, `WidgetDescriptor`, `FrontendConfig` — `SchemaBase`.

**Инварианты:**
1. Виджет не знает про IPC — координатор делегирует.
2. Конфиг рядом с виджетом (ADR-044): `components/<name>/config.py`.
3. Hot-reload через `ConfigManager.subscribe()` (ADR-036).
4. PyQt5-импорты — через `core/qt_imports.py` (точка стабилизации).

**Зависимости:** `process_module`, `router_module`, `data_schema_module`, `logger_module`. Внешние: `PyQt5`.
**Тестов:** ~150+

---

## Сводная таблица

| Модуль | LOC | Слой | Зависимости | Тестов |
|--------|----:|------|-------------|-------:|
| `base_manager` | 2 188 | L1 | — | 30+ |
| `data_schema_module` | 16 168 | L1 | — | 80+ |
| `dispatch_module` | 3 447 | L2 | base | 56 |
| `channel_routing_module` | 2 093 | L2 | base, schema, dispatch | 58 |
| `message_module` | 2 616 | L3 | schema | 50+ |
| `router_module` | 3 225 | L3 | crm, message, dispatch | 80+ |
| `logger_module` | 1 705 | L4 | crm | 40+ |
| `error_module` | 1 026 | L4 | logger | 25+ |
| `statistics_module` | 1 500 | L4 | crm | 40+ |
| `shared_resources_module` | 5 233 | L5 | base | 50+ |
| `config_module` | 2 393 | L5 | base, schema | 49 |
| `command_module` | 1 220 | L6 | dispatch, base | 34 |
| `worker_module` | 2 356 | L6 | base | 49 |
| `process_module` | 3 965 | L7 | worker, router, logger, srm, schema | 60+ |
| `console_module` | 2 877 | L7 | base, schema, logger | 40+ |
| `process_manager_module` | 4 612 | L8 | process, command | 80+ |
| `sql_module` | 3 775 | L9 | base, schema | 70+ |
| `registers_module` | 1 169 | L10 | schema | 30+ |
| `frontend_module` | 12 039 | L11 | process, router, schema, logger | 150+ |

**Итого:** 19 модулей, ~73 634 LOC (с тестами), 670 файлов.
