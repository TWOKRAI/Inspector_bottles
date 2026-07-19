# Module Contracts — Контракты модулей

**Назначение:** для каждого из 25 модулей указано: цель, публичный контракт (`interfaces.py` + ключевые классы), обязательные инварианты, входы/выходы, зависимости. Документ — параллельная сетка к [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md): тот навигатор «когда применять», этот — «что обязано быть». Границы и разбор путающих осей — [`MODULES_RESPONSIBILITY_MAP.md`](MODULES_RESPONSIBILITY_MAP.md).

**Обновлено:** 2026-07-12 — C8 docs-sync: `recipe` контракт дозаписан по факту C2/C3 (реестр step-миграций + generic `yaml_io`, ADR-RCP-003/005); `process_manager_module` — контракт топологии (`SystemBlueprint`/`ProcessConfig`/`Wire`, ADR-PMM-016) + `infer_missing_inspectors` (ADR-PMM-017); инварианты `process_manager_module` перекодированы `ADR-PM-*` → `ADR-PMM-*` (коды переименованы ранее, ADR-PMM-001…006, документ не был обновлён).
**Ранее** 2026-07-11 — добавлен контракт `recipe` (крыша над рецептами, C1/ADR-RCP-001/002); счётчик 24 → **25**.
**Ранее** 2026-07-08 — добавлены контракты `event_module`, `actions_module`, `service_module`, `display_module` (сверка с фактом); `sql_module` вынесен в `Services/sql` (раздел Storage → заметка).
**Ранее** 2026-05-07 — `state_store_module` актуализирован под ADR-SS-011/012/013, `chain_module` — под ADR-CHN-006/007 (renamed из ADR-CM-*; код модуля **CHN**, не **CM** — последний за `console_module`).

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

### `state_store_module`

**Цель:** Реактивное иерархическое дерево состояния с server/client разделением между процессами.

**Контракт:**
- `IRouter` (Protocol) — `register_message_handler`, `send_async`, `send`; RouterManager реализует без изменений (ADR-SS-001).
- `IStateStore` (ABC) — `get`, `get_subtree`, `set`, `merge`, `delete`.
- `IStateProxy` (ABC) — `get`, `set`, `merge`, `subscribe`, `unsubscribe`, `on_state_changed`.
- `IStateStoreManager` (ABC) — `initialize`, `shutdown`, `use`, `register_commands`, `register_message_handlers`.
- `StateStoreManager(BaseManager, ObservableMixin, IStateStoreManager)` — серверный фасад, живёт в `ProcessManagerProcess`. Содержит `TreeStore + SubscriptionManager + DeltaDispatcher`.
- `StateProxy(BaseManager, ObservableMixin, IStateProxy)` — клиентский прокси в каждом `ProcessModule`. Кэширует подписанные пути; **фильтрует входящие дельты per-pattern** (ADR-SS-012) — callback видит только дельты своей подписки.
- `GuiStateProxy(StateProxy)` — Qt-safe вариант: callbacks через `QMetaObject.invokeMethod` (QueuedConnection); ленивый импорт `PySide6` (ADR-SS-005).
- `TreeStore` — иерархический dict с dot-notation путями и delta-генерацией. Glob-обход узлов делегирован общему `core/glob_walker.py`.
- `Delta` — `path`, `old_value`, `new_value`, `source`, `timestamp`.
- `DeltaDispatcher` — адресная (по `targets`) рассылка дельт подписчикам с дедупликацией (ADR-SS-008).
- `SubscriptionManager` — glob-паттерны + `match(delta) -> list[Subscription]`. Публичные snapshot-методы `subscribers_snapshot()` / `subscriptions_for(subscriber)` для shutdown и DevTools (ADR-SS-013) — приватные атрибуты больше не дёргаются извне.
- `match_pattern`, `split_pattern` — публичные хелперы glob-матчинга (ADR-SS-004).
- `StateMiddleware` (ABC) — `before_set/after_set`, `before_merge/after_merge`, `before_delete/after_delete`.
- `MiddlewarePipeline` — цепочка middleware (пустой pipeline — нулевой overhead).
- `ValidationMiddleware` — поддерживает `rule['type']` как одиночный тип или `tuple[type, ...]`.
- `PersistenceManager` — доменно-нейтральный (ADR-SS-011): принимает `file_mapping: dict[str, Path]` (root → файл) и опциональные `path_predicate` / `value_filter`. Без жёстко зашитых имён файлов (`recipes.yaml`, `settings_recipes.yaml` и т.п.) — конфигурируется приложением.
- `RecipeEngine` — **переехал в модуль `recipe`** (C1, ADR-RCP-001); `state_store_module.recipes` — тонкий шим-реэкспорт.
- `InMemoryRouter` — тестовый router без IPC (синхронная диспатч), экспортирован публично (ADR-SS-010).

**Инварианты:**
1. `IRouter` — Protocol (не конкретный `RouterManager`); внешняя зависимость через утиную типизацию.
2. `StateStoreManager` (сервер) живёт в `ProcessManagerProcess`; `StateProxy` (клиент) — в каждом рабочем процессе.
3. Доставка только delta-only: полный snapshot **не** рассылается, только изменившиеся узлы.
4. `GuiStateProxy` импортирует `PySide6` лениво — тестируется без Qt.
5. `PersistenceManager` не знает доменных имён — список файлов и предикаты передаются приложением (после ADR-SS-011).
6. `StateProxy` фильтрует дельты по pattern до вызова callback (после ADR-SS-012).

**Зависимости:** `base_manager`, `pyyaml`. Внешние: опционально `PySide6` (lazy).
**Тестов:** 421

---

### `recipe`

**Цель:** Крыша над управлением рецептами: snapshot/restore config-ветвей, распознавание формата (v3-blueprint vs config-snapshot), точка миграций через callbacks, CRUD-менеджер. Доменных схем не знает — пути/миграции/yaml-writer инжектируются.

**Контракт:**
- `StoreProtocol` (Protocol) — `has`, `get`, `transaction`; доменно-нейтральный срез `TreeStore`. Движок типизирует store через него и **не импортирует** `state_store_module` (нет цикла).
- `RecipeEngineProtocol` (Protocol) — `save / load / list / delete / set_active / deactivate / get_active / is_dirty / recipes_dir`.
- `RecipeManagerProtocol` (Protocol) — то же + `duplicate / read_recipe` + синхронизация `state.recipes.active`.
- `RecipeEngine` — snapshot/restore; миграции через `migration_fn` / `migration_check_fn` (ADR-SS-003) либо через реестр `run_chain` как дефолт (`doc_type` в `__init__`+Protocol, явный `migration_fn` приоритетен); доменные ветви через `default_paths` (ADR-RCP-001, паттерн ADR-SS-011). v3-blueprint (`is_v3_recipe`) на `load()` помечается active без replay/migrate/write.
- `RecipeManager` — CRUD + state-sync; `duplicate()` по умолчанию пишет comment-preserving через **generic writer модуля** `recipe.yaml_io.update_yaml_preserving` (C3, ADR-RCP-005); `yaml_updater=` — опциональная инъекция для подмены (напр. plain-PyYAML без ruamel), через detect-стратегию формата (`is_v3_recipe`).
- `migration(doc_type, from_, to)` / `registered_steps(doc_type)` / `run_chain(doc_type, data, from_version, to_version)` — реестр step-миграций, `doc_type`-namespaced (C2, ADR-RCP-003); сами шаги (доменные dict-трансформации) регистрируются прикладным слоем.
- `is_v3_recipe` — единая точка распознавания формата.
- `normalize_recipe_v3_raw` — единая сборка v3-raw на запись.

**Инварианты:**
1. Фреймворк не знает доменных ветвей рецептов — `default_paths` инжектируется приложением (ADR-RCP-001).
2. Модуль не импортирует `state_store_module` — store только через `StoreProtocol` (нет цикла recipe ↔ state_store).
3. v3-blueprint никогда не реплеится в store и не перезаписывается миграцией (generic-ветвь в `load()`).
4. `duplicate()` использует `yaml_io` модуля по умолчанию (writer generic, живёт в модуле) — комментарии сохраняются без прикладной инъекции; `yaml_updater=` нужна только для подмены writer'а (C3, ADR-RCP-005; отменяет прежнюю схему ADR-RCP-002, где инъекция была обязательна).
5. Модуль НЕ собирает топологию — `assembler`/`planner` в его состав не входят (сейчас в `multiprocess_prototype/backend/assembly/`, будущий дом — `process_manager/topology`, ADR-RCP-005).

**Границы:** реестр `@migration`/`run_chain` (C2) и generic `yaml_io` + переработка `duplicate()` (C3) — сделано, ADR-RCP-003/005. Доменные схемы (пути, шаги-миграции) — инжектируются приложением. Физический перенос `assembler`/`planner` — отдельная process_manager-задача, вне scope модуля.
**Зависимости:** `pyyaml`, stdlib. Store — через `StoreProtocol`.
**Тестов:** 98

---

## L6 — Events (in-proc)

### `event_module`

**Цель:** Generic typed in-proc pub/sub — синхронная шина «фактов» с диспетчеризацией по `type(event)`.

**Контракт:**
- `EventBusProtocol` (Protocol) — `subscribe(event_type, handler) -> Subscription`, `publish(event) -> None`.
- `EventBus` — реализация; опц. `error_handler: (exc, event) -> None`. Хранит подписчиков по `type`.
- `Subscription` — дескриптор подписки: `unsubscribe()`; поддерживает context-manager (`with bus.subscribe(...) as sub`).
- `ErrorHandler` — тип колбэка ошибок.

**Инварианты:**
1. Диспетчеризация строго по `type(event)` — подписчик на тип A не видит подтипы/другие типы.
2. Шина **не знает** доменных типов событий — доменные dataclass-события живут в приложении/плагине.
3. **In-proc** и синхронно: не для межпроцессной доставки (это `EventManager` в `shared_resources_module`), не для команд (`dispatch_module`), не для реактивного состояния (`state_store_module`).
4. Leaf: зависимостей от других модулей фреймворка нет.

**Зависимости:** — (stdlib).
**Тестов:** +

---

## L7 — Command & Work

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

### `actions_module`

**Цель:** Action-bus с undo/redo и coalescing для GUI — отменяемые мутации состояния (carve-out из `frontend_module/actions/`, ADR-124).

**Контракт:**
- `Action(SchemaBase)` — иммутабельная единица изменения: `forward_patch`, `backward_patch`, `coalesce_key`.
- `ActionBus` — единая точка выполнения: `execute(action)`, `undo()`, `redo()`, coalescing по `coalesce_key`, опц. журнал через `IActionLogWriter`.
- `ActionBuilder` — generic-фабрика действий (приложения наследуют для доменных методов); `from_field()` принимает объект с `register_name`/`field_name` (локальный Protocol `RegisterBindingLike`).
- `ActionHandler` — обработчик применения патча.
- `IRegistersManagerGui` (Protocol) — контракт менеджера регистров для GUI (`ActionBus` работает с любым, кто его реализует; PySide6 не требуется).
- `SnapshotHistory` / `SnapshotEntry` — история снимков для undo/redo.
- `persistence/interfaces.py`: `IActionLogWriter`, `IActionLogRepository` — контракты для Services (реализация writer'а — в `Services/sql/action_log/`).

**Инварианты:**
1. `Action` иммутабельна; откат — через `backward_patch`, не мутацией.
2. Модуль **не зависит** от `frontend_module` и PySide6 — только `IRegistersManagerGui` Protocol.
3. Конкретный лог-writer — в Services; framework знает только Protocol-контракт (правило слоёв, ADR-120).
4. Ось «действия с undo/redo» ≠ `command_module` (IPC-команды `имя→handler`, без отката).
5. **Статус:** прод-undo в прототипе идёт через domain `CommandDispatcherOrchestrator`, `ActionBus` как прод-путь не задействован; модуль сохраняется как building-block (решение владельца 2026-07-08; ADR-COMM-002 об удалении не исполняется).

**Зависимости:** `data_schema_module`.
**Тестов:** +

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

### `chain_module`

**Цель:** DAG/Chain execution engine для pipeline-операций обработки кадров.

**Контракт:**
- `IChainRunnable` (Protocol) — `execute(frame, metadata) -> ChainResult`.
- `IStepNode` / `IStepNodeWithWorker` (Protocol) — дескриптор ноды графа (`node_id`, `operation_ref`, `inputs`, опц. `worker_id`).
- `INodeConnection` (Protocol) — соединение между нодами (`source`, `input_port`, `output_port`).
- `IExecutionStep` (Protocol) — операция: `execute(data, context)`, `configure(params)`.
- `IRemoteExecutable` (Protocol, ADR-CHN-006) — явный контракт cross-process шага: атрибут `dispatcher` + метод `execute_remote(frame, context, input_shm_name, input_shm_index)`. Поддерживается всеми тремя исполнителями.
- `IChainLogger` (runtime_checkable Protocol, ADR-CHN-008) — узкий публичный логгер исполнителей: `log_info`, `log_warning`, `log_error`. Любой `BaseManager + ObservableMixin` удовлетворяет через duck-typing (после ADR-CHN-008 `ObservableMixin` имеет публичные `log_*` алиасы).
- `ChainRunnable` — последовательный исполнитель списка `RunnableStep`.
- `DagRunnable` — исполнитель DAG (ветвления 1→N и слияния N→1 через именованные порты).
- `ParallelChainRunnable` — параллельные бандлы через `ChainThreadPool`. В бандле cross-process шаги выполняются синхронно (через `execute_remote`), local — через пул.
- `ChainContext` — контекст выполнения: `camera_id`, `region_id`, `seq_id`, `warnings`, `errors`, `timeouts`, `logger: IChainLogger | None` (ADR-CHN-008).
- `ChainResult` — результат: `frame`, `detections`, `skipped_nodes`, `failed`, `fail_level`, `processing_time`.
- `RunnableStep` — шаг: `node: IStepNode`, `operation: IExecutionStep`, `on_error`. Cross-process определяется через `_is_cross_process(step)` (duck-typing по `IRemoteExecutable`).
- `apply_on_error_policy(step, exc, context, result) -> bool` — единая on_error логика (skip / fail_region / fail_camera) для всех трёх исполнителей (ADR-CHN-006). DRY.
- `WorkerPoolDispatcher(BaseManager, ObservableMixin)` — round-robin маршрутизация задач в worker pool через IPC+SHM (ADR-CHN-007). Метрики `worker_pool.dispatched/timeouts/drops/late_responses/errors` (counter) и `worker_pool.processing_time` (timing).
- `WorkerTaskRequest / WorkerTaskResponse` — Dict-at-Boundary IPC-протокол обмена с worker-процессом.
- `ChainThreadPool(BaseManager, ObservableMixin)` — обёртка над `ThreadPoolExecutor` с timeout и graceful shutdown.
- `LatencyTracker(BaseManager, ObservableMixin)` — measurement queue + p50/p95/p99 (numpy linear interpolation, точно для маленьких N). Каждый `record()` пишется как timing метрика `<name>` (default `chain.latency_ms`); `maybe_log()` публикует snapshot `.p50/.p95/.p99`.
- `topological_sort`, `detect_parallel_bundles`, `is_nonlinear_graph` — graph utilities (Кан + bundle detection).

**Инварианты:**
1. Execution objects (`ChainRunnable`, `DagRunnable`, `ParallelChainRunnable`) — **не** менеджеры; не наследуют `BaseManager` (создаются на каждый `RegisterRuntime.rebuild()`).
2. Долгоживущие сервисы (`ChainThreadPool`, `WorkerPoolDispatcher`, `LatencyTracker`) — наследники `BaseManager + ObservableMixin`; принимают `logger=None`, `stats=None`, `errors=None` опционально.
3. Logger исполнителей передаётся через `ChainContext.logger` (тип `IChainLogger | None`, ADR-CHN-008); если не задан — тихо. `error_policy` зовёт `log_warning`/`log_error` (публичные методы).
4. Граница фреймворк/прототип: builder.py (load_operation_class) и конкретные операции остаются в прототипе (ADR-CHN-003, ADR-CHN-004).
5. on_error логика — единственная точка истины в `core/error_policy.apply_on_error_policy` (ADR-CHN-006).
6. Cross-process шаги определяются через `IRemoteExecutable` Protocol (ADR-CHN-006); сигнатура `execute_remote(frame, context, input_shm_name, input_shm_index)` зафиксирована.

**Зависимости:** `base_manager`. Внешние: `numpy`.
**Тестов:** 67

---

## L8 — Process

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

## L9 — Orchestration

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
- `topology/blueprint.py` — schema-модель топологии всей системы (не одного процесса): `SystemBlueprint` (`processes: list[ProcessConfig]`, `wires: list[Wire]`), `ProcessConfig` (typed-поля `inspector`/`chain_targets`/`source_target_fps`/`io_peek` — приоритет над одноимёнными в `extras`; `extras`/`metadata` — domain-opaque мешки), `Wire`, `Port`. Переехало из `process_module/generic/blueprint.py` (C6 (c), ADR-PMM-016) — системный артефакт живёт у оркестратора, не у модуля одного процесса; back-compat шим на старом пути удалён (grouping Фаза 2, 2026-07-19) — импорт только из `topology/`.
- `SystemBlueprint.infer_missing_inspectors()` — структурный вывод `{mode: join, inputs, primary}` для процессов без явного `inspector`: ≥2 процесса-источника REQUIRED-порта → join (опциональные порты не считаются); явный `inspector`/`extras["inspector"]` — escape-hatch, отключает вывод. Заменяет снятый костыль `_hoist_inspector_from_metadata` (Ф4.7, ADR-PMM-017).
- `TopologyManager` (`process/topology_manager.py`) — runtime-применение топологии (switch/hot-apply); отдельный от `blueprint.py` (runtime-логика применения vs schema-модель).

**Инварианты:**
1. **Per-process stop events** (ADR-PMM-001): остановка одного не затрагивает других.
2. **Минималистичный ProcessSpawner** (ADR-PMM-002): только SRM + signal, без ConfigManager/LoggerManager/ErrorManager.
3. **Bundle Contract** (ADR-PMM-003): pickle-safe формализованный dict для дочернего процесса.
4. **Heartbeat monitoring** (ADR-PMM-004): `process.is_alive()` для обнаружения crashed.
5. **Signal handler** только устанавливает `stop_event`, **не вызывает `sys.exit()`** (ADR-PMM-006).
6. **Топология — артефакт оркестратора** (ADR-PMM-016): `SystemBlueprint`/`ProcessConfig`/`Wire` живут в `topology/`, не в `process_module`.
7. **join — структурный факт графа wires** (ADR-PMM-017): не зависит от того, куда в рецепте попал `inspector` (прямой ключ vs `metadata`); тег входа = имя source-порта совпадает с `data_type` только по конвенции (не проверяемый инвариант схемы) — см. известные edge-случаи в `modules/process_manager_module/DECISIONS.md`.

**Зависимости:** `process_module`, `command_module`.
**Тестов:** ~80+

---

## L10 — Registries (реестры сущностей)

### `service_module`

**Цель:** Реестр и lifecycle-метаданные long-running сервисов (камеры, БД-подключения, auth-провайдеры) — generic, без знания о конкретных реализациях (ADR-129).

**Контракт:**
- `IService` (Protocol) — контракт сервиса с явным жизненным циклом.
- `ServiceLifecycle(Enum)` — `UNREGISTERED → READY → RUNNING → STOPPED → ERROR`.
- `ServiceRegistry` (singleton) — `register/get/list`, `ServiceEntry` (метаданные записи).
- `@register_service` — декоратор регистрации.
- `discover(*dirs) -> DiscoveryResult` — сканер директорий сервисов.

**Инварианты:**
1. Generic-компонент: не знает о `Services/`, `Plugins/`, `multiprocess_prototype/` — инстанцирование и запуск на application-слое.
2. В отличие от `PluginRegistry` — **без hot-reload**, расширенный lifecycle-автомат.
3. Реестр **сервисов** ≠ реестр регистров (`registers_module`) ≠ реестр дисплеев (`display_module`).

**Зависимости:** `base_manager` (+ stdlib).
**Тестов:** 91 (`registry` 26 + `scanner` 15 + …).

---

### `display_module`

**Цель:** Декларативный реестр именованных SHM-каналов отображения кадров (blueprint) — generic, без vision-семантики (ADR-130).

**Контракт:**
- `DisplayEntry` (dataclass) — описание канала (имя, метаданные; без numpy shape/dtype).
- `IDisplayRegistry` / `IDisplayChannel` (Protocol) — контракты реестра и канала.
- `DisplayRegistry` (singleton, thread-safe) — `register(entry)`, `persist(path)`/`load(path)` (YAML).

**Инварианты:**
1. Модуль **не создаёт** SHM-сегменты — только blueprint; создание при старте делает `SharedResourcesManager` (ADR-025).
2. Не знает о numpy/vision — конкретный shape/dtype вычисляет prototype-слой.
3. Реестр **SHM-каналов кадров** ≠ прочие реестры (см. семейство в `MODULES_RESPONSIBILITY_MAP.md`).

**Зависимости:** stdlib + `pyyaml`.
**Тестов:** 12.

---

> **Storage — `sql_module`** вынесен в `Services/sql` (Phase 4.1, ADR-121): `SQLManager`, `DDLBuilder`, `QuerySet[T]`, `GenericRepository[T, ID]`, `UnitOfWork`/`AsyncUnitOfWork`, `TableExporter`, Dict-at-Boundary команды. Инварианты (immutable QuerySet, fork-safe `NullPool`, ленивый async-адаптер) — там же. Контракт: [`../../Services/sql/README.md`](../../Services/sql/README.md).

---

## L11 — Application kit

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

## L12 — UI (опционально)

### `frontend_module`

**Цель:** PySide6-фреймворк виджетов с привязкой к регистрам.

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
4. PySide6-импорты — через `core/qt_imports.py` (точка стабилизации).

**Зависимости:** `process_module`, `router_module`, `data_schema_module`, `logger_module`. Внешние: `PySide6`.
**Тестов:** ~150+

---

## Сводная таблица

| Модуль | LOC | Слой | Зависимости | Тестов |
|--------|----:|------|-------------|-------:|
| `base_manager` | 2 188 | L1 | — | 30+ |
| `data_schema_module` | 16 168 | L1 | — | 80+ |
| `message_module` | 2 616 | L1/L3* | schema | 50+ |
| `dispatch_module` | 3 447 | L2 | base | 56 |
| `channel_routing_module` | 2 093 | L2 | base, schema, dispatch | 58 |
| `router_module` | 3 225 | L3 | crm, message, dispatch | 80+ |
| `logger_module` | 1 705 | L4 | crm | 40+ |
| `error_module` | 1 026 | L4 | logger | 25+ |
| `statistics_module` | 1 500 | L4 | crm | 40+ |
| `shared_resources_module` | 5 233 | L5 | base | 50+ |
| `config_module` | 2 393 | L5 | base, schema | 49 |
| `state_store_module` | ~3 300 | L5 | base | 421 |
| `recipe` | ~1 400 | L5 | pyyaml | 98 |
| `event_module` | ~150 | L6 | — | + |
| `command_module` | 1 220 | L7 | dispatch, base | 34 |
| `actions_module` | ~700 | L7 | schema | + |
| `worker_module` | 2 356 | L7 | base | 49 |
| `chain_module` | ~1 610 | L7 | base | 67 |
| `process_module` | 3 965 | L8 | worker, router, logger, srm, schema | 60+ |
| `console_module` | 2 877 | L8 | base, schema, logger | 40+ |
| `process_manager_module` | 4 612 | L9 | process, command | 80+ |
| `service_module` | ~500 | L10 | base | 91 |
| `display_module` | ~300 | L10 | pyyaml | 12 |
| `registers_module` | 1 169 | L11 | schema | 30+ |
| `frontend_module` | 12 039 | L12 | process, router, schema, logger | 150+ |

**Итого:** 25 модулей во фреймворке, ~76 750 LOC (с тестами). `sql_module` (~3 775 LOC) вынесен в `Services/sql` (Phase 4.1) — в счётчик фреймворка не входит.

\* `message_module` в SPEC.md классифицируется как L3 (Messaging), в карте слоёв `MODULES_OVERVIEW.md` — как L1-foundation для message-данных. Обе классификации валидны; зависит только от `data_schema_module`.
