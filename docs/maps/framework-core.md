# Карта framework — сырьё для модели архитектуры (C4)

Снято 2026-10-26 на HEAD `71bfc55fe` в ходе аудита фундамента ([опись](../reports/2026-10-26_foundation-audit-inventory.md)). Это не диаграмма, а данные, разложенные по уровням C4: из них собирается модель (кандидат — LikeC4, архитектура-как-код) и строятся виды по контурам. Устаревает с каждым коммитом. Здесь моментальный снимок, генератор и сторож «модель = код» — отдельная задача очереди (бриф CTO, вопрос 15).

Источники: ast-разбор импортов production-кода `multiprocess_framework/modules/` (тесты исключены), `rg` по интерфейсам, классам, потокам и IPC-примитивам (Haiku-агент, выборочно сверено), ярусы из [MODULE_TIERS.md](../../multiprocess_framework/docs/MODULE_TIERS.md), наследование из graphify.

Схемы по этим данным — [docs/diagrams/foundation-audit/index.html](../diagrams/foundation-audit/index.html): процессы (C4 L2), модули по контурам (L3), иерархия классов, три пути, счётчики рестарта. Кто хостит каждый сервис `Services/` и как `backend_ctl` достаёт до ядра — [опись 1б: Services](../reports/2026-10-26_foundation-audit-1b-services.md), [backend_ctl](../reports/2026-10-26_foundation-audit-1b-backend-ctl-libs.md).

## Как читать

- **id** — стабильный ключ узла для модели (`fw.<модуль>`). Имя модуля без `_module`.
- **контур** — предварительный тег для фильтров вида. Модуль может иметь несколько тегов:
  - `lifecycle` — запуск, остановка, супервизия процессов и потоков;
  - `ipc` — сообщения, каналы, очереди, разделяемая память;
  - `processing` — исполнение pipeline и кадров;
  - `state` — конфиг, состояние, регистры, рецепты;
  - `observability` — логи, ошибки, статистика, телеметрия;
  - `foundation` — базовые классы и схемы;
  - `ui` — GUI-слой.
- **ярус** — core / optional из `MODULE_TIERS.md`.

## Уровень 2 — контейнеры (процессы) и что в них живёт

| id | процесс | создаётся | что внутри (потоки, имена из кода) |
|---|---|---|---|
| `proc.launcher` | главный процесс, `SystemLauncher` | точка входа приложения | `ProcessSpawner` запускает PM: `multiprocessing.Process` (`launcher/spawner.py:108`), общее `system_stop_event` (`spawner.py:51`) |
| `proc.pm` | `ProcessManagerProcess` (наследник `ProcessModule`); в приложении — `GenericProcessManagerApp` (`app_module/orchestrator.py:38`) | `ProcessSpawner` | реестр детей `ProcessRegistry` (`Process(` — `core/process_registry.py:265`, свои `stop_event`/ready на ребёнка — `:306, :310`); `ProcessMonitor`; поток `ready-gate-{name}` (`process_manager_process.py:1694`); `backend_ctl`-эндпоинт (сокет) при `BACKEND_CTL=1` |
| `proc.child` | `ProcessModule` / `GenericProcess` | PM через `ProcessRegistry.create_and_register` | `parent-watch-{name}` (`runner/process_runner.py:167`); роутер: `router-sender-{name}` (`core/_sender.py:86`), `router-listener-{name}` (`core/_receiver.py:76`), `queue-ch-{name}` (`channels/queue_channel.py:153`); воркеры `{manager}_{worker}` (`worker_lifecycle.py:74, 103, 260`); `{manager}-retention` у логгера (`logger_core.py:881`); `batch-drain-{name}`, `async-sender-buffer` (channel_routing); `StateCoalesceFlusher` (`delta_dispatcher.py:297`) там, где подключён state_store |
| `proc.gui` | приложение PySide6 (`frontend_module`) | отдельный запуск прототипа | GUI-мост к роутеру; headless-режим живёт без него (MODULE_TIERS) |
| `ext.backend_ctl` | внешний клиент `backend_ctl` (MCP) | агент или оператор | сокет к PM: `socket-ch-accept/read/inbound-{name}` (`router_module/channels/socket_channel.py:162, 329, 474`), клиент `socket_client.py:250` |

**Состав дочерних процессов в коде не записан — его задаёт рецепт.** Таблица выше перечисляет типы процессов. Конкретный набор детей, их провода и плагины приложение получает из выбранного рецепта (принцип владельца 6: GUI формирует топологию, бэкенд исполняет headless). Значит, вид L2 для приложения строится по рецепту — один вид на рецепт (`multiprocess_prototype/recipes/`, 22 YAML), а не по коду. Цепочка по коду:

1. Вход: команда `recipe.activate` — `RecipeService` (`multiprocess_framework/modules/recipe/service.py:122`), подключается к PM в прототипе (`multiprocess_prototype/orchestrator.py:130–155`); исполнитель `pm-lifecycle-submit` (`orchestrator.py:81`).
2. PM: ретаргет адреса рецепта, затем `self.apply_topology(td)` (`process_manager_process.py:916`) → `apply_topology` (:4012) → `_topology_provision` (бамп `incarnation`, :4444) → `ProcessRegistry.create_and_register`.
3. Подробная карта смены рецепта — [recipe-switch.md](recipe-switch.md). Решение владельца 2026-10-13: единственный публичный вход — `recipe.activate`, а `topology.apply` — внутренняя команда, FREEZE (`docs/claude/memory/project_pipeline_recipe_driven_launch.md`).
4. Факт рядом, без оценки: GUI прототипа зовёт `proxy.apply_topology(blueprint, …)` напрямую — `multiprocess_prototype/frontend/widgets/tabs/pipeline/runtime_control.py:143, 227` (запуск активного рецепта и рестарт). Вопрос 16 брифа CTO.

Межпроцессные примитивы (L2-связи):
- `multiprocessing.Queue` / `ReaderGoneQueue` — очереди детей (`QueueRegistry`, `shared_resources_module/queues/core/manager.py`; `reader_gone.py:48–50`). Потоковые `queue.Queue` — внутри процесса (`queue_channel.py:36`, `events/core/manager.py:104`).
- `multiprocessing.Event` — свой стоп ребёнка и общий `system_stop_event`.
- `SharedMemory` — кадры (`memory/platform/shm.py:262, 278`; кольца `buffers/ring_buffer.py`), чтение `memory/reader/shm_frame_reader.py`.
- Сокет — `backend_ctl` ↔ PM.

## Уровень 3 — компоненты (модули ядра)

| id | ярус | контур | интерфейсы (`interfaces.py`) — публичные методы | `__all__` | главные классы (база) | README от |
|---|---|---|---|---|---|---|
| `fw.process_manager` | core | lifecycle | `ISystemLauncher`: add_process, run, start, wait_until_ready, stop, shutdown, wait, get_status, get_stats · `IProcessManagerProcess`: create/start/stop/restart_process, get_process_status, get_all_processes_status, apply_topology · `IProcessRegistry`: add_process, get_process_by_name, create_and_register, start_all, stop_all, stop_one, remove_process | 11 | ProcessManagerProcess(ProcessModule), SystemLauncher, ProcessSpawner, ProcessRegistry, ProcessMonitor, ProcessStatusMonitor, ProcessPriority | 2026-10-26 |
| `fw.process` | core | lifecycle, processing, ipc | `IProcessModule`: attach_stop_budget, initialize, shutdown, close_root, run, stop, should_stop, send_message, broadcast_message, receive_message, get_config, update_config, update_process_state, get_stats · `ISharedResources` · `IProcessCommunication` (Protocol): send, receive, send_to_process, broadcast, send_message, broadcast_message, receive_message, register_process_queues, register_router_channels, unregister_process, get_queue_stats | 35 | ProcessModule(BaseManager, ObservableMixin, IProcessModule), GenericProcess(ProcessModule), ProcessModulePlugin(ABC), ProcessIO, ProcessAdapter, ProcessLaunchConfig, TelemetryPublishConfig | 2026-10-13 |
| `fw.router` | core | ipc | `IRouterManager`: send, send_async, receive, start/stop_listening, add/remove_message_callback, register/unregister/get_channel, get_all_channels, register_route, register_broadcast_route, register_message_handler, add_send/receive_middleware, clear_middleware, get_stats · `IMessageChannel(IChannel)`: send, write, poll, close, start/stop_listening, get_info | 16 | RouterManager(ChannelRoutingManager), MessageChannel, QueueChannel, RouterAdapter, FrameShmMiddleware, RouteDecision | 2026-10-19 |
| `fw.channel_routing` | core | ipc, observability | `IChannel`: write, close, get_info · `IBufferStrategy`: enqueue, flush, start, stop, stats · `IChannelRoutingManager(IBaseManager)`: register/unregister/get_channel, get_all_channels, flush, reconfigure | 16 | ChannelRoutingManager(BaseManager, ObservableMixin, IChannelRoutingManager), ChannelRegistry, AsyncSenderBuffer, DirectBuffer, ObservabilityHub, BoundedChannel | 2026-09-06 |
| `fw.shared_resources` | core | ipc | `interfaces.py` — только реэкспорт из `core/interfaces.py`: `ISharedResourcesManager`: initialize, shutdown, register/unregister_process, reinitialize_in_child, get_process_data, get_all_process_data, get_process_config, get_process_names, for_process, has_process, broadcast, get_all_statuses + свойства registry/store/manager; плюс IConfigStore, IQueueRegistry, IEventManager, IMemoryManager, IProcessStateRegistry | 33 | SharedResourcesManager, EventManager, QueueRegistry, MemoryManager (все BaseManager + ObservableMixin + свой I*), ConfigStore, RingBufferWriter/Reader, ShmRegistry | 2026-09-24 |
| `fw.state_store` | optional | state, ipc | `IRouter` (Protocol): register_message_handler, send_async, send · `IStateStore`: get, get_subtree, set, merge, delete, revision · `IStateProxy`: get, set, merge, delete, subscribe, unsubscribe, on_state_changed · `IStateStoreManager`: initialize, shutdown, use, register_commands, register_message_handlers | 30 | StateStoreManager, StateProxy (BaseManager), DeltaDispatcher, TreeStore(IStateStore), SubscriptionManager, PersistenceManager, StateMiddleware | 2026-08-24 |
| `fw.chain` | core | processing | `IExecutionStep`: execute, configure · `IChainRunnable`: execute · `IRemoteExecutable`: execute_remote · `IStepNode`, `IStepNodeWithWorker`, `INodeConnection`, `IChainLogger` | 24 | ChainRunnable, DagRunnable, ParallelChainRunnable, ChainThreadPool(WorkerPoolExecutor), WorkerPoolExecutor, WorkerPoolDispatcher, LatencyTracker (BaseManager) | 2026-10-13 |
| `fw.worker` | core | lifecycle, processing | `OrderedExecutor`: submit, request_stop, join_until, shutdown · `IExecutorManager`: create, register, load_config, names, describe, is_executor_thread · `IWorkerRegistry` · `IWorkerLifecycle`: create/start/stop/restart_worker · `IWorkerManager` (27 методов: create/start/stop/restart/remove/pause/resume/drain worker, *_all_workers, статус, метрики) | 14 | WorkerManager(BaseManager, ObservableMixin, IWorkerManager), ExecutorManager, WorkerAdapter, WorkerLifecycle, ThreadConfig | 2026-10-21 |
| `fw.command` | core | ipc | `ICommandManager(IBaseManager)`: register_command, log_registration_summary, handle_command, get_commands, get_command_info, get_commands_by_tag, update_command_metadata, update_command_tags, overwrite_command | 6 | CommandManager, CommandAdapter, BaseCommandManager | 2026-10-21 |
| `fw.message` | core | ipc, foundation | `IMessage` (Protocol): set_priority, set_targets, add_target, set_channel, add_metadata, validate, is_valid, to_dict, to_json, get, clone, get_schema_info | 30 | Message(SchemaBase), MessageAdapter, MessageContractRegistry | 2026-07-14 |
| `fw.logger` | core | observability | `ILogChannel(IChannel)` · `ILoggerManager(IBaseManager)`: log, debug, info, warning, error, critical, system, business, performance, audit, security, push/pop_context, set/clear_base_context, flush, get_stats, should_log, is_enabled_for | 36 | LoggerManager(LoggerCore), LoggerCore(ChannelRoutingManager), LogChannel, FileChannel, ConsoleChannel, HttpChannel, RouterPushChannel, StdLoggerFacade, ErrorFloor | 2026-09-01 |

У всех 11 модулей ядра есть README.md, STATUS.md и DECISIONS.md. CONTEXT.md нет ни у одного.

### Остальные 16 модулей

| id | ярус | контур | `__all__` | главные классы (база) |
|---|---|---|---|---|
| `fw.base_manager` | core | foundation | 8 | BaseManager(IBaseManager), ObservableMixin, BaseAdapter — база 20 менеджеров |
| `fw.data_schema` | core | foundation | 84 | SchemaBase, FieldMeta, FieldRouting, DataConverter (по MODULE_TIERS; grep классов не завершён) |
| `fw.dispatch` | core | ipc | 7 | Dispatcher(BaseManager), DispatchStrategy, HandlerInfo, Scenario |
| `fw.error` | core | observability | 3 | ErrorManager(LoggerCore, IErrorManager) |
| `fw.statistics` | core | observability | 13 | StatsManager(ChannelRoutingManager), ObservationManager(ChannelRoutingManager) |
| `fw.config` | core | state | 6 | ConfigManager(BaseManager, …), Config, ConfigFileWatcher |
| `fw.console` | core | observability | 9 | ConsoleManager(BaseManager, …) |
| `fw.app` | optional | lifecycle | 28 | GenericProcessManagerApp(ProcessManagerProcess), ManifestStore, AppManifest |
| `fw.registers` | optional | state, ui | 12 | RegistersManager(BaseManager), FieldInfo |
| `fw.recipe` | optional | state | 14 | RecipeEngine, RecipeManager |
| `fw.display` | optional | ui | 4 | DisplayEntry, IDisplayChannel, IDisplayRegistry |
| `fw.service` | optional | lifecycle | 8 | ServiceHost, IService, DiscoveryResult |
| `fw.frontend` | optional | ui | 23 | PySide6-слой; Protocol-ы SupportsCommandMessage, IRouterLike, IRegistersManager |
| `fw.actions` | optional | ui, state | 7 | Action(SchemaBase), ActionBuilder, ActionBus |
| `fw.event` | optional | ui | 5 | EventBus, EventBusProtocol |
| `fw.telemetry_readmodel` | optional | observability, ui | 3 | TelemetryReadModel, ITelemetryReadModel |

У всех 27 модулей есть `interfaces.py`. Одинаковые имена в разных модулях: `IRegistersManager` (`registers_module/interfaces.py:14` и `frontend_module/interfaces.py:51`, плюс копия в `frontend_module/bridge/command_validator.py:39`), `DiscoveryResult` (`app_module/discovery.py:49` и `service_module/scanner.py:35`).

Наследование (graphify) — [class-hierarchy.mmd](../diagrams/foundation-audit/class-hierarchy.mmd).

## Связи модулей (ast, production-код)

Всего 110 рёбер «модуль → модуль», 426 импортов. Из них 218 (51 %) идут через `interfaces.py` или корень пакета, 208 — вглубь (`<модуль>.core.x` и т.п.). Импортов из framework в `Services` / `Plugins` / `multiprocess_prototype` — 0. Модули без исходящих рёбер: display, service, telemetry_readmodel.

Наиболее глубокие рёбра (вглубь / всего): `process_manager → process` 21/23, `process → logger` 21/26, `process → router` 11/14, `app → process` 11/11, `process → statistics` 9/12, `process → config` 9/11, `process_manager → shared_resources` 8/12, `app → process_manager` 7/7, `process → channel_routing` 7/7, `process_manager → logger` 7/10.

Рёбра «снизу вверх» — из фундамента или наблюдаемости в процессный слой; это список для сторожа, не вердикт: `data_schema → process` (2), `data_schema → shared_resources` (1), `statistics → process` (2), `state_store → recipe` (1). Все идут вглубь, мимо `interfaces.py`. Ребро `data_schema → frontend`, которое агент нашёл через `rg`, ast не подтвердил.

## Кто снаружи пользуется framework (ast, без тестов)

Прототип, `Services` и `Plugins` в этой карте раскрыты только как потребители. Их собственные процессы, плагины и рецепты — уровни C4 L1–L2 для приложения — отдельная задача.

| слой | файлов с импортом framework | импортов | по модулям (убывание) |
|---|---|---|---|
| multiprocess_prototype | 187 | 324 | frontend 108, logger 64, registers 22, process 18, data_schema 16, actions 14, recipe 14, state_store 14, service 12, app 11, display 10, process_manager 7, router 4, event 2, config 2, worker 2, channel_routing 2, base_manager 1, message 1 |
| Plugins | 158 | 302 | process 277, error 4, message 3, data_schema 3, logger 3, state_store 3, recipe 3, router 2, base_manager 2, channel_routing 2 |
| Services | 71 | 106 | process 39, logger 25, data_schema 13, base_manager 9, service 9, actions 4, channel_routing 3, router 2, _fallback 1, frontend 1 |
| backend_ctl | 13 | 20 | process 8, telemetry_readmodel 2, channel_routing 2, process_manager 2, message 1, error 1, logger 1, base_manager 1, app 1, router 1 |

Плагины ходят почти только в `process` (277 из 302) — это `PluginContext` / `ProcessModulePlugin`, как требует ADR-120. Импорты в обратную сторону (framework → эти слои) — 0.

Диаграмма модулей — [module-deps.mmd](../diagrams/foundation-audit/module-deps.mmd).

### Относительные импорты, которые выходят за `modules/` (сверено запуском, light)

| файл:строка | импорт | что происходит | с какой даты |
|---|---|---|---|
| process_module/__init__.py:118, 122, 126 | `from ...process_manager_module.topology.blueprint import SystemBlueprint / ProcessConfig / Wire` (ленивый `__getattr__`) | `process_module.SystemBlueprint` → `ModuleNotFoundError: No module named 'multiprocess_framework.process_manager_module'` (на одну точку больше нужного). Вызывающих по этому имени нет | 2026-07-11 · 4a1d0a722 |
| shared_resources_module/adapters/data_schema_adapter.py:29 | `from ....data_schema_module.storage.storage_manager import StorageManager` | цель `multiprocess_framework.data_schema_module` не существует, `except ImportError: return None` (:31) — `get_data_manager()` всегда `None`; модуль лежит в `modules/data_schema_module/storage/storage_manager.py` | ≤ 2026-04-30 |
| router_module/interfaces.py:16 | `from ...message_module import Message` под `TYPE_CHECKING` | в рантайме не исполняется; для pyright путь ведёт в несуществующий пакет | — |

### Все рёбра

Колонки: всего импортов / через `interfaces.py` или корень пакета / вглубь.

| from → to | всего | iface/root | вглубь |
|---|---|---|---|
| process_module → logger_module | 26 | 5 | 21 |
| frontend_module → logger_module | 25 | 22 | 3 |
| process_manager_module → process_module | 23 | 2 | 21 |
| process_module → data_schema_module | 20 | 16 | 4 |
| process_module → router_module | 14 | 3 | 11 |
| frontend_module → data_schema_module | 13 | 13 | 0 |
| process_manager_module → shared_resources_module | 12 | 4 | 8 |
| process_module → statistics_module | 12 | 3 | 9 |
| app_module → process_module | 11 | 0 | 11 |
| process_module → config_module | 11 | 2 | 9 |
| statistics_module → channel_routing_module | 11 | 8 | 3 |
| process_manager_module → logger_module | 10 | 3 | 7 |
| logger_module → channel_routing_module | 9 | 5 | 4 |
| process_module → worker_module | 9 | 6 | 3 |
| process_manager_module → data_schema_module | 8 | 8 | 0 |
| process_module → base_manager | 8 | 3 | 5 |
| app_module → process_manager_module | 7 | 0 | 7 |
| process_module → channel_routing_module | 7 | 0 | 7 |
| router_module → message_module | 6 | 6 | 0 |
| config_module → data_schema_module | 5 | 2 | 3 |
| process_module → message_module | 5 | 5 | 0 |
| process_module → console_module | 5 | 1 | 4 |
| shared_resources_module → base_manager | 5 | 4 | 1 |
| error_module → logger_module | 4 | 0 | 4 |
| process_manager_module → error_module | 4 | 4 | 0 |
| process_manager_module → config_module | 4 | 0 | 4 |
| process_manager_module → message_module | 4 | 0 | 4 |
| process_module → state_store_module | 4 | 3 | 1 |
| router_module → shared_resources_module | 4 | 0 | 4 |
| shared_resources_module → logger_module | 4 | 2 | 2 |
| statistics_module → logger_module | 4 | 2 | 2 |
| worker_module → base_manager | 4 | 3 | 1 |
| actions_module → logger_module | 3 | 3 | 0 |
| app_module → state_store_module | 3 | 0 | 3 |
| base_manager → logger_module | 3 | 0 | 3 |
| chain_module → base_manager | 3 | 3 | 0 |
| channel_routing_module → data_schema_module | 3 | 3 | 0 |
| channel_routing_module → logger_module | 3 | 0 | 3 |
| command_module → base_manager | 3 | 2 | 1 |
| console_module → base_manager | 3 | 2 | 1 |
| error_module → channel_routing_module | 3 | 1 | 2 |
| frontend_module → message_module | 3 | 2 | 1 |
| frontend_module → router_module | 3 | 0 | 3 |
| message_module → data_schema_module | 3 | 3 | 0 |
| process_manager_module → base_manager | 3 | 2 | 1 |
| process_module → registers_module | 3 | 2 | 1 |
| process_module → command_module | 3 | 2 | 1 |
| registers_module → data_schema_module | 3 | 3 | 0 |
| worker_module → data_schema_module | 3 | 3 | 0 |
| app_module → data_schema_module | 2 | 1 | 1 |
| channel_routing_module → base_manager | 2 | 2 | 0 |
| config_module → base_manager | 2 | 2 | 0 |
| data_schema_module → logger_module | 2 | 2 | 0 |
| data_schema_module → process_module | 2 | 0 | 2 |
| error_module → data_schema_module | 2 | 2 | 0 |
| event_module → logger_module | 2 | 2 | 0 |
| frontend_module → base_manager | 2 | 2 | 0 |
| frontend_module → shared_resources_module | 2 | 0 | 2 |
| process_manager_module → router_module | 2 | 0 | 2 |
| process_module → error_module | 2 | 1 | 1 |
| router_module → channel_routing_module | 2 | 2 | 0 |
| router_module → config_module | 2 | 0 | 2 |
| state_store_module → base_manager | 2 | 2 | 0 |
| statistics_module → data_schema_module | 2 | 2 | 0 |
| statistics_module → process_module | 2 | 0 | 2 |
| actions_module → data_schema_module | 1 | 1 | 0 |
| app_module → recipe | 1 | 1 | 0 |
| app_module → config_module | 1 | 0 | 1 |
| base_manager → data_schema_module | 1 | 1 | 0 |
| base_manager → channel_routing_module | 1 | 0 | 1 |
| base_manager → error_module | 1 | 0 | 1 |
| chain_module → worker_module | 1 | 1 | 0 |
| command_module → data_schema_module | 1 | 1 | 0 |
| command_module → dispatch_module | 1 | 1 | 0 |
| command_module → worker_module | 1 | 1 | 0 |
| config_module → logger_module | 1 | 1 | 0 |
| config_module → shared_resources_module | 1 | 0 | 1 |
| console_module → logger_module | 1 | 1 | 0 |
| console_module → data_schema_module | 1 | 1 | 0 |
| data_schema_module → shared_resources_module | 1 | 0 | 1 |
| dispatch_module → base_manager | 1 | 1 | 0 |
| event_module → base_manager | 1 | 1 | 0 |
| frontend_module → registers_module | 1 | 1 | 0 |
| frontend_module → state_store_module | 1 | 1 | 0 |
| frontend_module → process_module | 1 | 0 | 1 |
| frontend_module → actions_module | 1 | 0 | 1 |
| frontend_module → event_module | 1 | 1 | 0 |
| frontend_module → telemetry_readmodel_module | 1 | 1 | 0 |
| logger_module → data_schema_module | 1 | 1 | 0 |
| logger_module → base_manager | 1 | 1 | 0 |
| process_manager_module → worker_module | 1 | 1 | 0 |
| process_manager_module → command_module | 1 | 1 | 0 |
| process_manager_module → console_module | 1 | 1 | 0 |
| process_module → chain_module | 1 | 1 | 0 |
| process_module → shared_resources_module | 1 | 0 | 1 |
| recipe → logger_module | 1 | 1 | 0 |
| registers_module → base_manager | 1 | 1 | 0 |
| registers_module → logger_module | 1 | 1 | 0 |
| router_module → base_manager | 1 | 0 | 1 |
| router_module → logger_module | 1 | 1 | 0 |
| router_module → data_schema_module | 1 | 1 | 0 |
| router_module → dispatch_module | 1 | 1 | 0 |
| router_module → command_module | 1 | 1 | 0 |
| shared_resources_module → data_schema_module | 1 | 1 | 0 |
| shared_resources_module → config_module | 1 | 0 | 1 |
| state_store_module → logger_module | 1 | 1 | 0 |
| state_store_module → router_module | 1 | 0 | 1 |
| state_store_module → recipe | 1 | 0 | 1 |
| statistics_module → base_manager | 1 | 0 | 1 |
| worker_module → logger_module | 1 | 1 | 0 |
