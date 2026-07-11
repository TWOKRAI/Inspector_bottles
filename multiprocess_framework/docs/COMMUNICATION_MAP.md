# Карта коммуникаций Inspector_bottles (framework + prototype)

> Авто-сгенерировано многоагентным аудитом (workflow comms-architecture-audit) 2026-05-31.
> Покрытие: 23 подсистем, 166 механизмов, gap-fill раундов: 2.
> Сырые структурированные карты + аудит RouterManager — в COMMUNICATION_MAP_raw.json (рядом).

---

# Канонический документ: Карта механизмов коммуникации Inspector_bottles

> Источник: структурированная карта 12 подсистем + 5 gapfill, отчёт критика, аудит центральности RouterManager.
> Принцип владельца: **чем меньше звеньев — тем стабильнее**. Документ ориентирован на сокращение путей.

---

## 1. Инвентарь цепочек по типу данных

Сводка: 9 классов данных. Для каждого — таблица цепочек с диаграммой звеньев, модулями, признаком cross-process, слоем и статусом alive/dead.

### 1.1 Команды (command)

| Цепочка (звенья) | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| GUI worker CRUD: `WorkerBridge._send → CommandSender.send_command → ProcessModule.send_message → ProcessCommunication.send_to_process → queue_registry.send_to_queue('{proc}_system')` → (в процессе) `RouterManager.receive → message_dispatcher → CommandManager.handle_command → BuiltinCommands._cmd_worker_*` | worker_bridge, frontend_module/bridge, process_module, command_module, worker_module | да | mixed | **alive** |
| GUI system-команды: `TopologyBridge → CommandSender.send_system_command('process.command') → send_message('ProcessManager') → ProcessManagerProcess._handle_process_command → command_manager.handle_command → _cmd_process_*/_cmd_wire_*/blueprint.replace` | topology_bridge, frontend_module/bridge/system_commands, process_manager_module, command_module | да | mixed | **partial** (часть cmd живы; `process.hot_add`/`hot_remove` — мисматч, нет handler) |
| Console God Mode: `ConsoleAdapter._on_input → CommandManager.handle_command` | console_module, command_module | нет | framework | **partial** (только при `console.interactive`) |
| `CommandAdapter.execute_via_message → process.message_manager.create_command_message → router.send` | command_module/adapters | да | framework | **dead** (нет `message_manager`/`create_command_message`) |
| SQL IPC: `CommandManager → SQLManager.execute_command(db.query/execute/insert) → adapter → Engine` | Services/sql | да | framework | **dead** (нет регистрации `register_command('db.query', ...)` нигде кроме README) |

**Двойная диспетчеризация (живой путь):** один ключ `'command'` резолвится дважды — сначала `message_dispatcher` (router-уровень, lambda-обёртка), затем `CommandManager.dispatcher` (command-уровень). Два инстанса `Dispatcher` с зеркальными таблицами на каждый процесс.

### 1.2 Data-кадры (data-frame)

| Цепочка (звенья) | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| **Производство кадров (живой data-plane):** `SourceProducer.run_loop → plugin.produce() → FrameShmMiddleware(generic).strip_and_write [frame→SHM] → send_fn=send_message → queue_registry.send_to_queue('{target}_data')` | process_module/generic, shared_resources MemoryManager | да | framework | **alive** |
| **SHM-payload (numpy):** `strip_and_write → MemoryManager.write_images → SharedMemory.buf` … `restore_frame → MemoryManager.read_images ИЛИ SharedMemory(name=shm_actual_name)` | shared_resources_module/memory, buffers | да | framework | **alive** (через очередь идут только координаты) |
| Приём+fan-in: `DataReceiver.run_loop → receive_message(channel_types=['data']) → restore_frame → InspectorManager.on_item [буфер по (camera_id,seq_id)] → chain_queue.put` | process_module/generic | да | framework | **alive** |
| Внутрипроцесс: `chain_queue (queue.Queue) → PipelineExecutor.run_loop → _execute_chain → _send_results` | process_module/generic | нет | framework | **alive** |
| GUI-приём: `GuiProcess._data_receiver_loop → router.receive(['data']) → FrameShmMiddleware(router).on_receive → DataReceiverBridge.dispatch → ImagePanelWidget` | frontend/process, router_module/middleware | да | mixed | **alive** |
| RingBufferWriter/Reader (round-robin + seq_id) | shared_resources_module/buffers | да | framework | **partial** (реализован, но live-pipeline использует FrameShmMiddleware, дубль логики кольца) |
| `register_broadcast_route('frame.camera_{id}')` | frame_router_setup, router_module | да | mixed | **partial** (маршруты зарегистрированы, но live-трафик их не кормит) |

### 1.3 State-дельты (state)

| Цепочка (звенья) | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| **Live-телеметрия (долг #1, U1):** `ProcessMonitor._publish_state → StateStoreManager.handle_state_set [in-process] → TreeStore.set → DeltaDispatcher.dispatch_single → _send_state_changed(targets=['gui']) → RouterManager.send_async → _deliver_by_targets → queue_registry.send_to_queue('gui_system')` → `GuiStateProxy.on_state_changed → _StateDeltaEmitter → DataReceiverBridge → GuiStateBindings → виджеты` | process_manager_module/monitor, state_store_module, frontend/process+state | да | mixed | **alive** |
| Плагин-write: `Plugin._publish_state → ctx.state_proxy.merge → send_async → _deliver_by_targets('ProcessManager','system') → handle_state_merge → TreeStore.merge` | Plugins, state_store_module | да | mixed | **alive** (единственный живой write из дочерних) |
| `StateProxy.set` (скаляр) | state_store_module/proxy, adapters | да | mixed | **partial** (адаптеры в GUI с proxy=None → no-op) |
| `state.get/get_subtree` (pull-чтение) | state_store_module | да | framework | **dead** (нет прод-вызовов вне тестов) |
| **legacy broadcast:** `ProcessMonitor.broadcast_full_status → communication.broadcast → queue_registry.broadcast_message (subtype='process_full_status')` | process_manager_module/monitor | да | framework | **partial** (шлёт вхолостую, 0 потребителей в prototype) |

### 1.4 Domain-события (event) — внутри GUI

| Цепочка (звенья) | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| `QtEventBus.publish(ProjectEvent) → EventBus.publish → handler` (main-thread pass-through / worker→Signal+QueuedConnection) | domain/event_bus, frontend/qt_event_bus | нет | prototype | **alive** |
| `CommandDispatcherOrchestrator.dispatch(ProjectCommand) → Project.apply → TopologyRepositoryStore.save → publish(TopologyReplaced) → ProjectHistory.record → _notify_change` | adapters/dispatch, domain | нет | mixed | **alive** (единственный живой command-engine) |
| `store-publish TopologyReplaced → PipelinePresenter/ProcessesTab full-reload + app.py→TopologyBridge.on_topology_changed` | adapters/stores, frontend tabs | нет | mixed | **alive** |
| `RecipeActivated` cross-tab highlight; `ProcessAdded` auto-layout | domain/events, pipeline/services tabs | нет | prototype | **alive** |
| **legacy ActionBus** `execute/undo/redo + handlers + middleware` | actions_module, frontend/actions | нет | mixed | **dead** (0 прод-вызовов execute; глобальный undo на domain) |

### 1.5 Регистры (register) и schema-каналы

| Цепочка (звенья) | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| **Живой field-write:** `SetPluginConfig → RegistersBackendFromManager.set_value → RegistersManager.set_field_value → _notify_observers [field-fan-out к виджетам]` | adapters/stores/registers_backend, registers_module, frontend components | нет | mixed | **alive** |
| **Domain→IPC мост:** `PluginConfigChanged → app.py._on_plugin_config_changed → RegistersManager.set_value → … → send_message(process)` | domain, frontend/app, registers_module | да | mixed | **alive** (единственный мост field-edit → живой процесс) |
| Worker-side приём: `IPC 'register_update' → PluginOrchestrator._on_register_update → rm.set_field_value → relay 'register_changed'→process_manager` | process_module/generic/plugin_orchestrator | да | framework | **partial** (receiver жив; GUI-sender мёртв — см. ниже) |
| `RegistersManager.subscribe_all → RegistersStateAdapter → StateProxy.set` (Widget→StateStore) | registers_module, backend/state/adapters | нет | mixed | **dead** (адаптер не инстанцируется в prod) |
| `set_send_callback → control_{channel} → FrontendRegistersBridge → router.send_message` | frontend_module/core/registers_bridge, frontend_manager | да | framework | **dead** (`FrontendManager` не строится в v3; контракт ключей не совпадает: `register_name` vs `register`) |
| `@register_plugin / @register_service → Registry.register` (catalog-feed) | process_module/plugins/registry, service_module | нет→да (rebuild в worker) | mixed | **alive** |
| `RouterSchemaAdapter` (FieldRouting.channel → route registry) | router_module/adapters/schema_adapter | нет | framework | **dead** |
| Recipe YAML (`save_raw/read_raw → recipes_dir/{slug}.yaml`) — **критик** | recipes/manager, adapters/stores/recipe_store, bootstrap | да (через ФС) | mixed | **alive** |
| system.yaml / user_overrides.yaml (Settings → диск → run_gui discovery) — **критик** | config/schemas, settings/yaml_io, services/presenter | да (через ФС) | mixed | **alive** |

### 1.6 Heartbeat

| Цепочка (звенья) | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| `ProcessHeartbeat._loop → send_message('ProcessManager', heartbeat_msg) → queue_registry.send_to_queue → ProcessMonitor._on_heartbeat_received → _last_heartbeat + _workers_status + _publish_state` | process_module/heartbeat, process_manager_module/monitor | да | framework | **alive** |
| Timeout→UNRESPONSIVE→авто-рестарт: `_monitoring_loop → _check_heartbeat_timeout → _try_auto_restart → restart_process` | process_manager_module/monitor, restart_policy | нет | framework | **alive** |

Heartbeat-msg несёт избыточную типизацию: `type='system'` + `subtype='heartbeat'` + `command='heartbeat'`; диспатч идёт только по `command`.

### 1.7 Логи / ошибки / статистика

| Цепочка (звенья) | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| `ObservableMixin._log_* → _call_manager('logger') → LoggerManager.log → BatchBuffer → FileChannel.write` | base_manager, logger_module, channel_routing_module | нет | framework | **alive** (242+ call-sites) |
| `_record_metric → StatsManager.record_metric → AggregationWindow → _do_flush → каналы` | statistics_module | нет | framework | **alive** |
| `_track_error → ErrorManager.track_error → _level_to_channel → warnings/errors/critical.log` | error_module | нет | mixed | **partial** (name-mismatch 'error'→fallback 'errors'; `_log_error` идёт в logger, не сюда) |
| `LoggerManager._route_via_router → Message(LOG, targets=['logger']) → router.send` | logger_module, message_module | да | framework | **dead** (нет процесса 'logger' в prototype) |
| Console-мосты (ConsoleLogChannel / ConsoleRedirector / interactive input) | console_module | нет | framework | **partial** (при включённой консоли) |

### 1.8 Прочие управляющие сигналы

| Цепочка | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| `WorkerInfo.stop_event / pause_event (threading.Event)` — per-worker | worker_module, process_module/generic | нет | framework | **alive** |
| `system_ready_event / stop_event (multiprocessing.Event)` | process_manager_module/launcher, runner | да | framework | **alive** |
| `EventManager system_events → router.send(channel='system_events')` | shared_resources_module/events | да | framework | **partial** (router-ветка обычно `router_manager=None`; локальные callbacks живут) |
| `AuthState.access_context_changed / current_user_changed (Qt Signal)` | frontend/state/auth_state, permission_gate | нет | mixed | **alive** |
| `ConfigStore pub/sub (_subscribers / Config._change_callbacks)` | adapters/stores/config_store, config_module | нет | prototype/framework | **dead** (set/subscribe не вызываются в prod) |

### 1.9 GUI-bridge (внутрипроцессные Qt-мосты)

| Цепочка | modules_involved | cross-proc | layer | alive |
|---|---|---|---|---|
| `DataReceiverBridge.dispatch → _deliver Signal (Queued) → callback + Signal.emit` (frame/state/command) | frontend/bridge_impl | нет (worker→main thread) | prototype | **alive** (живой класс — `bridge_impl.py`, не top-level `bridge.py`) |
| `GuiStateBindings._on_state_msg → match_glob → _PROP_SETTERS[prop](widget)` | frontend/state/bindings | нет | prototype | **alive** |
| `PreviewWindow._frame_signal → _update_frame_slot` (pop-out дисплей) | frontend/widgets/displays/preview_window | нет | prototype | **dead** (нет продюсера; `router_manager=None` в `DisplaysTab.create`) |
| `WireMetricsController/WireStatusMonitor` | pipeline/telemetry | нет | mixed | **partial** (UI-каркас, реальных данных нет — Phase 8 заглушка) |

---

## 2. Роль RouterManager: что реально идёт через него

### 2.1 Через RouterManager (по аудиту центральности)

**RouterManager — канонический RECEIVE-хаб, но НЕ send-хаб.**

- **Приём (всегда через router):** `SystemThreads._message_processing_loop → RouterManager.receive(['system']) → _poll_all_channels → QueueChannel.poll → recv-middleware → message_dispatcher`. То же для data: `DataReceiver → receive_message(['data'])`. Это единственная универсальная точка, где RouterManager реально центрелен.
- **Регистрация каналов/маршрутов/handler'ов** — владение RouterManager (`register_channel`, `register_message_handler`, `register_broadcast_route`).
- **Genuine channel-routed egress (единственный):** `EventManager.emit_event → RouterManager.send(channel='system_events')` — резолвится через `_resolve_channels` O(1) lookup. И то — router-ветка часто неактивна (`router_manager=None`).
- **"Through-router API, но exit через fallback":** все `state.*` (set/merge/subscribe/changed) и `state_proxy.merge` вызывают `RouterManager.send/send_async`, но channel не задан → `_resolve_channels` возвращает `[]` → `_deliver_by_targets` (U1) → `queue_registry.send_to_queue`. То есть входят через router-API, но **выходят через queue_registry по имени процесса**, не через channel-routing.

### 2.2 Явный список bypass'ов

| Bypass | Файл | crosses_process |
|---|---|---|
| **ГЛАВНЫЙ:** `ProcessModule.send_message → send_to_process → queue_registry.send_to_queue` (по имени процесса) | process_communication.py:182-208 | **да** |
| SourceProducer data-frame → send_message → queue | source_producer.py:_send_item | **да** |
| PipelineExecutor output → send_message → queue | generic_process.py:98-108 | **да** |
| ProcessHeartbeat → send_message('ProcessManager') → queue | process_heartbeat.py:86 | **да** |
| **SHM numpy payload** (write_images/read_images / прямой `SharedMemory(name=...)`) | frame_shm_middleware, memory_handle | **да** |
| `ProcessHandle.queue(qtype).send → send_to_queue` | process_handle.py:46-49 | **да** |
| `QueueRegistry.broadcast_message` (fan-out по всем процессам) | queues/core/manager.py:185-200 | **да** |
| `multiprocessing.Event` (system_ready, stop, pause) | spawner, process_runner, worker_module | **да** |
| Spawn bundle (queues/config/routing_map) | process_registry, bundle_contract | **да** |
| `process_state_registry` (Manager-proxy, статусы/очереди) | shared_resources/state | **да** |
| **Файловая система** (recipe `*.yaml`, system.yaml, user_overrides.yaml) — **критик** | recipes/manager, config/schemas | **да** (через ФС) |
| `@register_plugin/@register_service` (import-time singleton) — **критик** | registry singletons | нет (rebuild в worker — да) |
| env (`MULTIPROCESS_LOG_DIR`/`INSPECTOR_LOG_DIR`) — наследуется OS — **критик** | logger log_paths | **да** |
| EventManager local `_event_queue` + callbacks | events/core/manager | нет |
| RegistersManager field-callbacks; GUI frame→widget callback; Qt Signal/Slot; QtEventBus | registers_module, frontend | нет |
| `process_manager_proxy.replace_blueprint()` синхронный direct-call — **критик** | pipeline/presenter:1495 | **да** (был бы; dead в v3) |

### 2.3 Честный вердикт по тезису «всё через RouterManager»

**FALSE для сегодняшнего рантайма.** Тезис аспирационный, не фактический.

- По **числу сообщений**: ~80-90%+ cross-process трафика (data-frames, heartbeat, GUI-команды, register-релеи, broadcasts) идёт через bypass `send_message → queue_registry`.
- По **объёму байт**: ~99% (image payloads) идёт через OS SharedMemory, вообще не касаясь шины. По очереди едут только SHM-координаты.
- **Genuine channel-routed egress** — ровно один поток (`system_events`), и тот полу-активен.
- RouterManager центрелен **только на приёме** (`receive` — универсальный вход) и как **реестр**. На отправке его routing-механизм (channel_dispatcher / `_resolve_channels`) практически не задействован: либо явный `msg['channel']` (минует dispatcher), либо U1-fallback по targets (минует channel-routing).

Вывод: **RouterManager сегодня — это `receive()` + `_deliver_by_targets` + реестр каналов. Его «маршрутизация по каналам» — мёртвый вес для 99% трафика.**

---

## 3. Избыточность и мёртвые пути (с доказательствами)

### 3.1 Дубли транспорта (один и тот же mp.Queue, три API)

1. **Три пути доставки в очередь процесса:** `RouterManager.send → _resolve_channels → QueueChannel('{target}_{qtype}').send`; `RouterManager._deliver_by_targets → queue_registry.send_to_queue`; `ProcessCommunication.send_to_process → queue_registry.send_to_queue`. Все сходятся на одной `mp.Queue`, но через разную адресацию (channel-name vs process-name). Логика `targets→queue` продублирована в **3 местах** (`send_to_process`, `broadcast_message`, `_deliver_by_targets`).
2. **Два broadcast-механизма:** `queue_registry.broadcast_message` (по именам процессов из PSR) vs `register_broadcast_route` (channel fan-out). Не связаны.

### 3.2 Дубли создания сообщений

3. **Три способа создать command/data-сообщение:** `MessageAdapter.command()/data()` (только ProcessIO), `Message.create()` (LoggerManager + тесты), **ручной dict в `CommandSender`** (живой основной путь). Message-формат де-факто продублирован как «соглашение о ключах dict».
4. `message_factory.create_message/parse_message` — алиасы `Message.create/from_dict`, 0 прод-вызовов.
5. `CommandMessageSchema/LogMessageSchema (extra='forbid')` — только тесты; `_msg_schema` всё равно теряется при `to_dict()`.

### 3.3 Дубли движков

6. **Два dispatch-движка для pipeline:** `dispatch_module` CHAIN_MATCH/ScenarioManager (**dead**, 0 вызовов) vs `chain_module` ChainRunnable/DagRunnable (тоже **dead** в prototype, но это «более общая» реализация). Реальный data-plane — `PipelineExecutor._execute_chain` — не использует ни тот, ни другой.
7. **Два undo/redo-движка:** framework `ActionBus` (**dead**, 0 прод-`execute`) vs domain `CommandDispatcherOrchestrator` (**alive**, `window.set_undo_controller(app_services.commands)`). Зеркальные контракты.
8. **Два класса `FrameShmMiddleware`:** `router_module/middleware/` (для router send/recv, used by GUI on_receive) vs `process_module/generic/` (strip_and_write/restore_frame, used by data-plane). Идентичная SHM-логика. Router-вариант **on_send практически не кормится** (продюсер зовёт strip_and_write напрямую).
9. **Два ring-buffer'а:** `shared_resources/buffers/ring_buffer.py` (RingBufferWriter) vs FrameShmMiddleware собственный `_write_index%coll`. Live-pipeline использует второй.
10. **Две `DataReceiverBridge`:** `frontend/bridge.py` (top-level, QueuedConnection — **dead-дубль**, затенён пакетом) vs `frontend/bridge_impl.py` (AutoConnection — **живой**, резолвится через `bridge/__init__.py`).

### 3.4 Мёртвый код (с доказательством)

| Символ | Доказательство dead |
|---|---|
| `ActionBus.execute` | serena: ровно 2 non-test call-site (FormContext.write, RolesPanel) — оба за `form_ctx=None`/`_bus=None` guard. `_legacy_action_bus` (app.py:420) присвоен и не используется |
| `Dispatcher.dispatch_scenario` / ScenarioManager / ChainMatch | только `dispatch_module/tests/*` |
| PATTERN_MATCH / FALLBACK_MATCH / BaseDispatcher / DispatcherConfig | 0 прод-регистраций; всегда EXACT_MATCH |
| `register_route` (single), `register_channel_scenario`, `register_channel_handler` | ADR-RTR-006: zero callers, Phase 8 reserved |
| `RouterSchemaAdapter`, `routing_map.py` helpers | только определение + Protocol |
| `CommandAdapter.execute_via_message`, `MessageAdapter.create_message` | ссылаются на несуществующие `message_manager`/`create_command_message` |
| `state.get/get_subtree` | плагины используют только merge; GUI читает через push |
| `RegistersStateAdapter`/`CameraStateAdapter`/`DisplayStateAdapter` | 0 прод-инстанцирований; Service/Recipe — инстанцированы, но `state_proxy=None` (inert) |
| `FrontendRegistersBridge.send_callback` / `set_send_callback` | `FrontendManager` не строится в v3; + контракт ключей `register_name` ≠ `register` |
| `ConfigStoreFromManager.subscribe/.set`, `Config.subscribe` | 0 прод-вызовов (только Config.get); `FrontendManager._on_config_changed` — единственный подписчик, мёртв |
| `LoggerManager._route_via_router` | `enable_router_routing=True`, но процесса 'logger' нет → доставка в никуда |
| `PreviewWindow._on_frame_received` / `subscribe` | 0 callers; `DisplaysTab.create` не передаёт router |
| `WorkerPoolDispatcher` / `WorkerTaskRequest/Response` | нет `CrossProcessStep`, нет процесса-обработчика; сигнатура send_fn не совпадает |
| `SQLManager.execute_command` (db.query/execute/insert) | 0 прод-регистраций; только tests + README-сниппет |
| `process_manager_proxy.replace_blueprint` (sync launch) | proxy в config только в тестах; в prod — warning «proxy недоступен» |

### 3.5 Лишние звенья

- **Двойная диспетчеризация команды** (message_dispatcher → lambda → CommandManager.dispatcher) — handle_command лишнее звено: message_dispatcher уже нашёл бы handler.
- StateStore регистрирует 7 `state.*` handler'ов **дважды** (`register_commands` + `register_message_handlers`).
- Поле `msg['channel']='data'` у data-сообщений — vestigial (доставка по `queue_type` из `msg['type']`).
- `subtype='heartbeat'` не читается получателем.
- `_cmd_process_list` / `process.command.response` формируют ответы, гарантированно теряемые в Router (нет потребителя correlation_id).

---

## 4. Ревью: проблемы и риски (с severity)

### HIGH

1. **Расхождение «декларация vs реальность» в роли RouterManager.** Документация/ADR утверждают центральность роутера; рантайм — 99% трафика мимо channel-routing. Риск: новые разработчики добавляют channel-routes (как `frame.camera_N`), которые никогда не кормятся → растёт dormant-машинерия. *Доказательство:* аудит центральности, verdict FALSE.
2. **Разорванный GUI→worker register-write контракт.** Два «register_update» с несовместимыми ключами: GUI-emitter (мёртвый) шлёт `{register_name, field_name, value, snapshot}`, worker-receiver читает `{register, field, value}`. End-to-end правка поля плагина из GUI **не доходит до живого процесса** штатным register-путём (доходит только через `PluginConfigChanged → rm.set_value → send_message`, и то — это отдельный мост). Риск: разъезд GUI-state и runtime-state.
3. **RBAC field-edit дыра.** `PreAuthGuard.hook` и `AuditMiddleware` «wired but never fired» — висят на мёртвом `ActionBus.execute`. Правки полей идут через domain-dispatch, минуя RBAC-gate. *Доказательство:* gapfill ActionBus + память `command_engine_audit`.
4. **Статус процесса в 3 источниках без single-source-of-truth:** `process_state_registry` (SHM), `ProcessMonitor.previous_states` (кэш), `StateStore.processes.X.state.status`. Ручная синхронизация в `_handle_dead_process`/`_check_heartbeat_timeout`. Риск рассинхрона; `_active_wires.status` может «врать» (выставляется даже если `send_message` упал).
5. **`process.hot_add`/`hot_remove` мисматч:** `build_hot_add_process` генерит `cmd='process.hot_add'`, но в `_register_builtin_commands` есть только `process.create`. `handle_command` вернёт «команда не найдена». Live hot-add процесса частично сломан.

### MEDIUM

6. **Слишком много промежуточных звеньев в живых путях.** Пример worker CRUD: GUI → WorkerBridge → CommandSender → send_message → send_to_process → queue_registry → receive → _poll_all_channels → recv-mw → message_dispatcher → lambda → CommandManager.handle_command → dispatcher → handler. ~12 звеньев на одну команду. Каждое — точка отказа/латентности.
7. **Рассинхрон framework/prototype.** Framework несёт целые подсистемы, мёртвые в prototype: `FrontendManager`+`FrontendRegistersBridge`, `RouterSchemaAdapter`, `ActionBus`, `chain_module`, `WorkerPoolDispatcher`, `SQLManager.execute_command`. Это «конструктор-задел», но он создаёт ложное впечатление о том, как система работает.
8. **fire-and-forget везде.** `handle_command`-результат теряется в Router; `correlation_id`/`process.command.response` не потребляются. GUI узнаёт результат только косвенно через StateStore. Риск: тихие сбои команд (создание воркера упало — GUI не знает).
9. **Файловая система как нескоординированный канал.** Recipe `*.yaml` и `system.yaml`/`user_overrides.yaml` переносят blueprint/config между GUI-edit и runtime-launch, но это **не отражено в карте IPC** и не имеет схемы валидации на границе чтения (критик: runtime-reader `read_raw` на orchestrator-уровне не трассирован до прод-вызова — **требует проверки**).
10. **`ConfigStore` двойная реализация pub/sub** (`_subscribers` + `Config._change_callbacks`), обе мёртвы; `ConfigStoreFromManager.set` дёргает обе. Half-built (TODO Phase E).

### LOW

11. Name-mismatch `_track_error → 'error'` (None) → fallback `'errors'`. Работает, но хрупко.
12. `StatsManager` принимает `router_manager`, кладёт в `managers['router']`, никогда не использует.
13. Три пути лога в консоль (ConsoleChannel / ConsoleLogChannel / ConsoleRedirector) → возможен двойной вывод при `redirect_stdout`.
14. `subtype`/избыточная типизация heartbeat; `msg['channel']='data'` vestigial.
15. Top-level `frontend/bridge.py` — затенённый мёртвый дубль `bridge_impl.py`.

---

## 5. Рекомендация: единый минимальный подход

### 5.1 Один универсальный способ коммуникации

> ⚠️ **SUPERSEDED (2026-05-31) планом [`transport-router-hub`](../../../plans/_archive/2026-05-31_transport-router-hub/plan.md) / [ADR-COMM-001](../DECISIONS.md).**
> Эта рекомендация («оставить process-name + named-queue, channel-routing депрекейтить») была минимальной
> «асфальтировать тропу». Владелец выбрал **противоположное** направление: достроить хаб правильно —
> **`router.send(message)` как единственный вход, каналы по `kind` как канонический транспорт**, обходы убрать.
> Текст ниже сохранён для истории; актуальное решение — ADR-COMM-001/004. Находки §3 (мёртвый код) и §5.2
> (слияния дублей) остаются в силе и используются планом как материал.

**Оставить ОДИН механизм cross-process транспорта: адресация по ИМЕНИ ПРОЦЕССА + named-queue (`queue_registry.send_to_queue`) на отправке, `RouterManager.receive` + `message_dispatcher` на приёме.**

Обоснование (принцип владельца «меньше звеньев»): этот путь **уже несёт 99% трафика**. Channel-routing (`_resolve_channels`/channel_dispatcher/FieldRouting.channel) — надстройка, которая в проде почти не работает. Делаем фактический путь — каноническим, а не наоборот.

### 5.2 Ядро / слияния / депрекейт

**Остаются ядром:**
- `shared_resources_module` (queue_registry + PSR + MemoryManager/SHM) — нижний транспорт.
- `RouterManager` — но в **усечённой роли**: `receive()` + `message_dispatcher` (приём+диспатч) + `_deliver_by_targets` (отправка по targets). Channel-routing — в опциональный режим.
- `state_store_module` (реактивное дерево + DeltaDispatcher) — единственный state-канал.
- `dispatch_module` (только `Dispatcher` + EXACT_MATCH) — синхронный key→handler.
- `command_module` (CommandManager) — in-process реестр команд.
- domain `EventBus`/`CommandDispatcherOrchestrator` — единственный GUI command/event-движок.

**Сливаются:**
- Две `FrameShmMiddleware` → **одна** (вынести в framework как канонический frame-transport middleware; data-plane и GUI используют её же).
- `RingBufferWriter` ⟷ FrameShmMiddleware ring-логика → **один** ring-buffer.
- `MessageAdapter` + ручной dict в `CommandSender` → **один** конструктор сообщений (тонкая фабрика dict с обязательными `type/command/targets/data`).
- Две `DataReceiverBridge` → удалить top-level `bridge.py`, оставить `bridge_impl.py`.

**Депрекейтятся (удалить из framework):**
- `ActionBus` + handlers + middleware (мёртв; глобальный undo на domain). RBAC/audit перенести на domain-dispatch (см. ADR ниже).
- `chain_module` ScenarioManager/ChainRunnable/DagRunnable/ParallelChainRunnable/WorkerPoolDispatcher (либо вынести в отдельный «experimental» и не экспортировать из `__init__`).
- `dispatch_module` PATTERN/FALLBACK/CHAIN стратегии, BaseDispatcher, DispatcherConfig, scenarios.
- `RouterSchemaAdapter`, `routing_map` helpers, `register_route`(single)/`register_channel_scenario`/`register_channel_handler`.
- `FrontendManager` + `FrontendRegistersBridge` + `send_callback`/`control_{channel}` register-IPC (мёртв; field-write идёт через domain).
- `CommandAdapter.execute_via_message`, `MessageAdapter.create_message`, `message_factory.*`, `CommandMessageSchema/LogMessageSchema`.
- `LoggerManager._route_via_router` (нет процесса 'logger').
- `SQLManager.execute_command` command-surface (оставить library-API query/execute).
- `PreviewWindow` SHM-subscribe (либо дописать продюсер, либо удалить).
- `state.get/get_subtree` (если pull не нужен).

### 5.3 Целевая цепочка «как надо» (минимум звеньев) по типу данных

После выноса универсальных механизмов из прототипа во фреймворк (слой `framework → Services → Plugins → prototype`):

| Тип | Целевая цепочка (минимум звеньев) |
|---|---|
| **Команда** | `Sender.send_message(target, {type,command,data}) → queue_registry.send_to_queue` → `RouterManager.receive → message_dispatcher → CommandManager.handle_command → handler`. **Убрать двойную диспетчеризацию** (регистрировать прикладной handler прямо в message_dispatcher, без lambda-обёртки в CommandManager). |
| **Data-frame** | `Producer → FrameShmMiddleware.strip_and_write [frame→SHM] → send_message('{target}', {data, shm_ref}) → queue` → `receive(['data']) → restore_frame → chain_queue → PipelineExecutor`. Одна middleware, один ring-buffer. |
| **State-дельта** | `source → StateStoreManager.handle_state_set/merge → DeltaDispatcher → _deliver_by_targets → queue('{sub}_system')` → `GuiStateProxy.on_state_changed → bindings → widget`. Это **уже целевой путь** (долг #1); удалить legacy broadcast `process_full_status`. |
| **Domain-событие (GUI)** | `Presenter → CommandDispatcher.dispatch(cmd) → Project.apply → store.save → EventBus.publish(event) → подписчики`. Уже минимален. |
| **Register/field-edit** | `GUI → CommandDispatcher.dispatch(SetPluginConfig) → PluginConfigChanged → rm.set_value → send_message(process, {command:'set_config', data}) → queue`. **Единственный** мост; убрать send_callback/control_-путь. |
| **Heartbeat** | `ProcessHeartbeat → send_message('ProcessManager') → queue → ProcessMonitor → _publish_state(StateStore)`. Минимален; убрать `subtype`. |
| **Лог/ошибка/стат** | `ObservableMixin._log_*/_record_metric/_track_error → менеджер по имени → BatchBuffer → FileChannel`. In-process, не трогать. Убрать `_route_via_router`. |
| **Blueprint (recipe launch)** | **Один путь** вместо трёх (domain ActivateRecipe / IPC blueprint.replace / sync proxy). Рекомендация: `RecipesPresenter → CommandDispatcher.dispatch(ActivateRecipe) → recipe YAML read → send_system_command('blueprint.replace', 'ProcessManager') → _cmd_blueprint_replace`. Убить sync `process_manager_proxy` (мёртв) и YAML-as-channel сделать явным звеном с валидацией на чтении. |

### 5.4 Предлагаемые ADR

**ADR-COMM-001 «Named-queue + RouterManager.receive — единственный канонический cross-process транспорт».** ⚠️ *(superseded новой редакцией [ADR-COMM-001](../DECISIONS.md) 2026-05-31 — хаб строится через `router.send` + каналы по kind, а не «оставить named-queue». Текст ниже — первая редакция, для истории.)*
Решение: адресация исключительно по имени процесса (`targets` / `send_message(target, ...)`); channel-routing (FieldRouting.channel, `register_route`, channel_dispatcher) переводится в `deprecated`/experimental и удаляется из публичного API RouterManager. RouterManager сохраняет роли: приёмный хаб (`receive`+`message_dispatcher`), отправка по targets (`_deliver_by_targets`), реестр каналов для `receive`. Why: 99% трафика уже идёт так; убираем мёртвую маршрутизацию и расхождение декларация/реальность. Layer: framework. Reversible: migration-needed.

**ADR-COMM-002 «Единый GUI-движок команд/undo/RBAC/audit — domain CommandDispatcher; ActionBus удаляется».**
Решение: весь GUI-mutation/undo/redo идёт через `CommandDispatcherOrchestrator`; RBAC pre-gate и audit переносятся в domain-dispatch (pre-dispatch hook + post-dispatch listener) — закрывает HIGH-риск #3. `actions_module` (bus+handlers+middleware) удаляется из framework. Why: ActionBus мёртв (0 прод-execute), но висит как «второй движок» и держит мёртвую RBAC-инфраструктуру. Layer: mixed (framework удаление + prototype domain). Reversible: yes.

*(Дополнительно, опционально)* **ADR-COMM-003 «Один frame-transport middleware + один ring-buffer; SHM-payload — канонический data-plane bypass».** Узаконивает SHM-bypass как намеренный (не дефект), сливает две `FrameShmMiddleware` и два ring-buffer в по одному.

---

## 6. Влияние на план Фазы 2 (assigned_worker)

Контекст из памяти: долг #2 `assigned_worker` runtime — вариант A; задачи 2.1–2.6 включают in-process queue handoff и RouterManager fallback по targets из Фазы 1.

### Задевает ли рефактор задачи 2.1–2.6 — да, и в благоприятную сторону:

- **RouterManager fallback по targets (из Фазы 1) — это ровно `_deliver_by_targets` (U1).** ADR-COMM-001 **узаконивает** его как канонический путь, а не временный fallback. → Задачи Фазы 2, опирающиеся на «targets-fallback», получают стабильную опору; переименовать в плане «fallback» → «основной targets-транспорт», чтобы не создавать впечатление временности.

- **In-process queue handoff (2.x).** Целевая data-цепочка использует внутрипроцессную `chain_queue` (`DataReceiver → chain_queue → PipelineExecutor`) — это **уже канонический intra-process handoff**. Если 2.x вводит in-process queue для assigned_worker, **переиспользовать паттерн `chain_queue`** (queue.Queue + LOOP-worker через WorkerManager), а **не** возрождать `WorkerPoolDispatcher`/`chain_module` (мёртвые, ADR-COMM-001/003 их депрекейтят). Явно зафиксировать: assigned_worker handoff = `chain_queue`-стиль, не CrossProcessStep.

### Что скорректировать в `processes-workers-runtime-debts.md`:

1. **Добавить зависимость от ADR-COMM-001.** Перед реализацией 2.x зафиксировать: assigned_worker адресуется по имени процесса (`targets`), доставка через `_deliver_by_targets/queue_registry`. Не вводить новый channel.
2. **Запретить в задачах 2.1–2.6 реанимацию `WorkerPoolDispatcher`/`chain_module`/`CrossProcessStep`** — они мёртвы и противоречат «минимум звеньев». In-process handoff = `chain_queue` паттерн.
3. **Учесть fire-and-forget (MEDIUM #8).** Если 2.x требует подтверждения назначения воркера — НЕ полагаться на `process.command.response` (теряется). Использовать StateStore-телеметрию (долг #1 живой): процесс публикует `processes.X.workers.Y.assigned_worker` → GUI читает через bindings. Это согласуется с уже закрытым долгом #1.
4. **Worker control уже симметричен по имени процесса** (`WorkerBridge → send_command(process_name, 'worker.*')`), но `worker_restart`/`worker_stop` в presenter — partial-dead (нет прод-caller). Если Фаза 2 их задействует — добавить в `presenter` реальные вызовы (закрыть partial).
5. **Не задевает SHM/frame-транспорт** — assigned_worker это control-plane (команды/state), а не data-plane. SHM-рефактор (ADR-COMM-003) ортогонален Фазе 2.
6. **Снять с критического пути упоминания channel-routing** в задачах Фазы 2, если они там есть: assigned_worker не должен регистрировать `register_route`/broadcast-маршруты.

**Итог по Фазе 2:** коммуникационный рефактор **не блокирует** 2.1–2.6, а укрепляет их фундамент (узаконивает targets-транспорт и `chain_queue`-handoff). Корректировки в плане — декларативные (зафиксировать ADR-зависимость + запрет мёртвых движков + подтверждение через StateStore вместо response), не структурные.

---

**Файлы-якоря (абсолютные пути):**
- Транспорт-ядро: `d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\router_module\core\router_manager.py`, `...\shared_resources_module\queues\core\manager.py`, `...\process_module\communication\process_communication.py`
- State: `...\state_store_module\manager\delta_dispatcher.py`, `...\manager\state_store_manager.py`
- Domain-движок: `d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\adapters\dispatch\command_dispatcher.py`, `...\domain\event_bus.py`
- Мёртвые движки (кандидаты на депрекейт): `...\actions_module\bus.py`, `...\chain_module\`, `...\chain_module\worker_pool\dispatcher.py`, `...\frontend_module\core\registers_bridge.py`
- План Фазы 2: `processes-workers-runtime-debts.md` (ветка `feat/processes-workers-runtime`)
