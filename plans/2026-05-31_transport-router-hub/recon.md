# P0.1 — Recon: карта обходов RouterManager + форма dict-сообщений (актуализация)

- **Дата:** 2026-05-31
- **Ветка:** `feat/processes-workers-runtime` (план создаётся на ней; рефактор-ветка `refactor/transport-router-hub` ещё не создана)
- **Источник:** `multiprocess_framework/docs/COMMUNICATION_MAP.md` (§1–§3) + `COMMUNICATION_MAP_raw.json` (`router_audit.bypasses` — 12 шт., `through_router`, `maps` 23 подсистемы). Аудит датирован 2026-05-31.
- **Оговорка:** read-only снимок кода **на момент P0.1**. Подсчёт «прод-callers» сделан через `Grep`/`serena find_referencing_symbols`/`qex` (codegraph MCP в этом окружении **недоступен** — счётчики получены статически, могут недосчитывать динамические/рефлексивные вызовы). Все строки/символы процитированы по живому коду.
- **Что изменилось с момента аудита:** единственный merge после 2026-05-31 в разрезе коммуникаций — `574017fd` (live-телеметрия StateStore, долг #1). Он **уже** отражён в аудите (DeltaDispatcher = alive, U1). **Фаза 2 `assigned_worker` (runtime) — PENDING**, код data-plane (`SourceProducer`/`PipelineExecutor`/`send_message`) с момента аудита **не менялся**. Расхождений «аудит устарел из-за Фазы 1» нет; найденные расхождения — методологические (см. раздел «Расхождения»).

---

## Краткая модель «как есть» (для контекста таблиц)

- **`RouterManager.send` / `_do_send`** (`router_module/core/router_manager.py:152,156`): `middleware → _resolve_channels → channel.send`. Если канал не резолвится → **U1 fallback `_deliver_by_targets`** (`:212`) → `queue_registry.send_to_queue(target, qtype, msg)`. `qtype = msg["queue_type"] or ("system" if type=="command" else "data")`.
- **`_resolve_channels`** (`:585`): (1) явный `msg["channel"]` → O(1) lookup; (2) `channel_dispatcher.dispatch(key_field="command"|"type")`; (3) `[]`. Маршрутизация **по `type`/`command` на отправке в проде не задействована** — единственный зарегистрированный явный канал `system_events`.
- **`ProcessCommunication.send_to_process`** (`process_communication.py:182`) — **главный обход**: при наличии `queue_registry` зовёт `queue_registry.send_to_queue(target, qtype, msg)` **напрямую, минуя `router.send`/`_do_send`** (`:198-202`). `send_message` (`:273`) и `broadcast_message` (`:277`) — алиасы. `ProcessModule.send_message` (`core/process_module.py:498`) делегирует сюда.
- **Приём** всегда через `RouterManager.receive` (`:258`) → `_poll_all_channels` → `QueueChannel.poll` → recv-mw → `message_dispatcher.dispatch`.

---

## Таблица 1 — Обходы RouterManager (отправка)

> «жив?» = число найденных прод-вызовов (вне `tests/`). Целевой канал — по модели P0.2 (`MessageType → address-aware channel`). Объём миграции: S ≤ 1 call-site/тривиально; M — несколько call-sites/смена контракта; L — слияние подсистем/паритет-тесты.

| # | Call-site (file:symbol) | Жив? (прод-callers) | Текущие ключи dict | crosses_proc | Целевой MessageType | Целевой канал | Миграция |
|---|---|---|---|---|---|---|---|
| B1 | **ГЛАВНЫЙ.** `process_communication.py:182 send_to_process` → `queue_registry.send_to_queue`; алиасы `:273 send_message`, `:277 broadcast_message`; `core/process_module.py:498 send_message`/`:566 send_to_process`/`:504 broadcast_message` | **жив** (центральный транзит: heartbeat, wire.*, register-релеи, GUI-команды, data-frames, state — все идут сюда; десятки прод-вызовов через `process.send_message`/`services.send_message`) | определяются вызывающим; ключ выбора очереди — `type`/`queue_type` | да | по `type` сообщения | `SystemChannel`/`DataChannel` (address-aware над `queue_registry`) | **L** (P1.3: сделать тонким адаптером над `router.send`) |
| B2 | `source_producer.py:103 _send_item` → `send_fn=send_message` (wiring `generic_process.py:137`) | **жив** (live data-plane камера→процессор→дисплей) | `{target, type:"data", channel:"data", data:item}`; `item` уже содержит SHM-координаты (`shm_name/shm_index/shm_actual_name/width/height`) после `strip_and_write` | да | `DATA` | `DataChannel` (+ `FrameShmMiddleware`) | **M** (P3.1) |
| B3 | `pipeline_executor.py:158 _send_results` → `send_fn=send_message` (wiring `generic_process.py:102`) | **жив** (processed-frame хопы между процессами) | `{target, type:"data", channel:"data", data:item}` (идентично B2) | да | `DATA` | `DataChannel` (+ `FrameShmMiddleware`) | **M** (P3.1) |
| B4 | `process_heartbeat.py:86 _loop` → `services.send_message("ProcessManager", ...)` | **жив** (каждый дочерний процесс, period=5s) | `{type:"system", subtype:"heartbeat", command:"heartbeat", sender, timestamp, status, workers_status}` | да | `COMMAND` (диспатч по `command="heartbeat"`) | `SystemChannel` | **S** (P4.2; убрать vestigial `subtype`) |
| B5 | **SHM numpy payload.** `process_module/generic/frame_shm_middleware.py strip_and_write/restore_frame` → `MemoryManager.write_images/read_images`; `router_module/middleware/frame_shm_middleware.py:54 on_send/:118 on_receive`; fallback — прямой `SharedMemory(name=shm_actual_name)` (`router .../frame_shm_middleware.py:142`); `shared_resources_module/handles/memory_handle.py`; `process_module/io/process_io.py` | **жив** (наибольший объём байт; пиксели в OS SHM, по очереди — только координаты) | в очередь идёт только `data:{shm_name, shm_index, shm_actual_name, width, height}` (см. B2/B3) | да | `DATA` (Claim Check) | внутренняя деталь `DataChannel`/`FrameShmMiddleware` (узаконенный bypass) | **L** (P3.1 + ADR-COMM-003: слить два middleware и два ring-buffer) |
| B6 | `process_handle.py:46 ProcessHandle/QueueHandle.send` → `queue_registry.send_to_queue` (API `srm.for_process(name).queue(qtype).send`) | **мёртв в проде** (0 прод-callers; только `shared_resources_module/tests/*`; обёртка `shared_resources_manager.py:285 srm.broadcast` тоже без прод-callers) | произвольный dict | да | — | — | **S** (изоляция; P5-кандидат, НЕ удалять) |
| B7 | `queues/core/manager.py:185 QueueRegistry.broadcast_message` → loop `send_to_queue` по PSR; обёрнут `process_communication.py:214 broadcast`/`:233` | **частично** (через `process_monitor.py:499,548 broadcast_full_status` — шлёт `process_full_status` вхолостую, 0 потребителей в prototype) | `{type:"system", subtype:"process_full_status", processes, timestamp}` (см. `process_monitor.py:488-498`) | да | `COMMAND`/broadcast | `SystemChannel` fan-out | **S** (P3.2/P4.2: удалить legacy broadcast) |
| B8 | `state_store_module/proxy/state_proxy.py:108 set/:128 merge/:163 get/:198 get_subtree` → `_send`/`_send_sync` → `router.send_async`/`send` → нет канала → **U1** | **жив** (`set`/`merge`); `get`/`get_subtree` — **мёртвы** (только тесты) | set:`{type:"command",command:"state.set",targets:[server],data:{path,value,source}}`; merge:`{...command:"state.merge",data:{path,data,source}}`; get:`{...command:"state.get",data:{path,request_id}}` | да | `COMMAND` (диспатч по `command="state.*"`) | `SystemChannel` (или `StateChannel` для read-write API) | **M** (P3.2) |
| B9 | `state_store_module/manager/delta_dispatcher.py:98 _send_state_changed` → `router.send_async` → нет канала → **U1** | **жив** (live-телеметрия, долг #1 / U1 — единственный живой state-fanout) | `{type:"event", sender, targets:[subscriber], queue_type:"system", command:"state.changed", data:{deltas:[...]}}` | да | `STATE` (диспатч по `command="state.changed"`) | `StateChannel` | **M** (P3.2 — путь уже целевой, обернуть) |
| B10 | `shared_resources_module/events/core/manager.py:127 emit_event` → `router.send(channel="system_events")` **+** `:144 _event_queue.put` **+** `:148 _notify_subscribers` | **частично** (router-ветка — **единственный genuine channel-routed egress**, но обычно `router_manager=None`; callbacks/local-queue живут intra-process) | router-msg: `{type:"system_event", command:"system_event", channel:"system_events", sender, content, targets:["ProcessManager"]}` | да (router-ветка) / нет (callbacks) | `EVENT` | `EventChannel` | **M** (P3.3: убрать dual/triple-write) |
| B11 | `plugin_orchestrator.py:290 _on_register_update` → relay; `:261 send_data` (primary) **или** `:325 MessageAdapter.create_message`+`send_message` (fallback `_io is None`) | **частично** (receiver жив; relay `register_changed` идёт через `_io.send_data`; ветка `create_message` — **dead**, см. ниже) | relay-data: `{process_name, register, field, value}` (msg_type `register_changed`) | да | `COMMAND`/`DATA` | `SystemChannel` | **S** (P4.1/P4.2) |
| B12 | `logger_module/core/logger_manager.py:383 _route_via_router` → `Message(LOG, targets=["logger"])` → `router.send` | **мёртв-доставка** (gated `is_enabled("router_routing")` + `_router_manager`; процесса `logger` в prototype нет → доставка в никуда) | `Message(LOG, targets=["logger"], level, message, module)` | да (по замыслу) | `LOG` | `ILogChannel` (in-process) | **S** (P5: изолировать ветку) |

**Intra-process bypass'ы (не cross-process, остаются — НЕ мигрируются в транспорт):**
`EventManager` local callbacks (B10); `RegistersManager` field-callbacks (`registers_bridge.py` notify, виджеты `subscribe`); GUI frame→widget `set_frame_callback` (`frontend/app.py:583-603`); Qt Signal/Slot; `QtEventBus`. По аудиту `crosses_process=false`. Лог в файл (B12 файловый sink) — per-process, не шина.

**Не-сообщенческие «каналы» (вне scope транспорта, для полноты):** `multiprocessing.Event` (system_ready/stop/pause), spawn bundle, `process_state_registry` (Manager-proxy), ФС (recipe/system.yaml — критик), env (LOG_DIR), `@register_plugin/@register_service` import-time singleton.

---

## Таблица 2 — Приём (RouterManager.receive / message_dispatcher) — ОСТАЁТСЯ

| Точка | file:symbol | Канал(ы) | Статус |
|---|---|---|---|
| System-команды | `process_module/threads/system_threads.py:70 _message_processing_loop` → `router_manager.receive(channel_types=['system'])` | `{proc}_system` | **жив, канонический** |
| Data-кадры | `process_module/generic/data_receiver.py run_loop` → `process.receive_message(channel_types=['data'])` (`process_communication.py:281`) | `{proc}_data` | **жив, канонический** |
| Диспатч | `router_manager.py:295-301 receive` → `message_dispatcher.dispatch(key_field="command"|"type")` | — | **жив**; единый incoming-диспетчер |
| Регистрация handler | `register_message_handler` (`router_manager.py:455`): `process.command` (`process_manager_process.py:161`), `state.set/merge/get/changed/...` (StateStoreManager) | — | **жив** |
| GUI data-приём | `frontend/process.py:64` router `FrameShmMiddleware` (recv) → `DataReceiverBridge.dispatch` (`bridge_impl.py`) | `gui_data` | **жив** |

> Вывод аудита подтверждён: RouterManager **центрелен на приёме** (универсальный `receive`) и как реестр каналов/handler'ов. На отправке его channel-routing задействован практически только для `system_events` (и тот полу-активен). Целевая модель P1–P4 оживляет отправку, **не трогая приёмную половину**.

**Двойная диспетчеризация (живое лишнее звено, §3.5):** `message_dispatcher` находит handler для `command` → lambda-обёртка → `CommandManager.dispatcher` (второй `Dispatcher` с зеркальной таблицей на процесс). Цель P4.4 — регистрировать прикладной handler прямо в `message_dispatcher`.

---

## Таблица 3 — Мёртвый код §3.4 — перепроверка

| Символ | Прод-callers | Вердикт | Примечание (для P5, НЕ удалять без approval) |
|---|---|---|---|
| `ActionBus.execute` | 2 (`frontend/app.py:420` — присвоение `_legacy_action_bus`, НЕ execute; `roles_panel.py:206 self._bus.execute` — за `form_ctx/_bus` guard) | **мёртв** | undo на domain `CommandDispatcherOrchestrator` (`window.set_undo_controller(app_services.commands)`, `app.py:502`). Делегировано в `constructor-maturity P1`, не сюда |
| `Dispatcher.dispatch_scenario` / `ScenarioManager` / `chain_match` | 0 прод (внутренняя делегация `dispatcher.py:355-380` + tests); **0 прод-регистраций сценариев** в prototype | **мёртв** | Strategy CHAIN/scenarios никогда не активируется (всегда EXACT_MATCH) |
| `PATTERN_MATCH`/`FALLBACK_MATCH`/`BaseDispatcher`/`DispatcherConfig` | 0 | **мёртв** | всегда `EXACT_MATCH` |
| `chain_module` `ChainRunnable`/`DagRunnable`/`WorkerPoolDispatcher`/`WorkerTaskRequest/Response` | 0 в prototype | **мёртв** (в prototype) | конструктор-задел; «более общий» движок чем `PipelineExecutor`. Реальный data-plane не использует |
| `register_route` (single) | 0 прод (tests: `channel_routing/tests`, `router_module/tests`) | **мёртв** | Но `register_channel`/`register_broadcast_route` — **живы** (см. ниже). Депрекейтить только routing-by-single-pattern |
| `register_broadcast_route` | **жив** (`frame_router_setup.py:49,67,81`) | **частично** | маршруты `frame.camera_{id}` зарегистрированы, но live SourceProducer шлёт `channel="data"`/`targets`, не `frame.camera_N` → routes не кормятся (dormant) |
| `register_channel_scenario`/`register_channel_handler` | 0 | **мёртв** | Phase 8 reserved |
| `RouterSchemaAdapter`, `routing_map` helpers | 0 (tests `test_schema_adapter.py`) | **мёртв** | — |
| `CommandAdapter.execute_via_message` | 0 прод (tests `test_command_adapter.py`) | **мёртв** | ссылается на несуществующие `message_manager`/`create_command_message` |
| `MessageAdapter.create_message` | **символ НЕ существует** на `MessageAdapter` (есть `.command()`/`.data()`); вызовы `plugin_orchestrator.py:273,325` — в ветке `else (self._io is None)` | **мёртв (dead branch)** | при `_io=None` упадёт `AttributeError`; primary-путь — `_io.send_data`. Free-func `message_factory.create_message` (`message_factory.py:18`) — 0 прод-callers, отдельный алиас |
| `state.get`/`state.get_subtree` | 0 прод (tests) | **мёртв** | плагины используют только `merge`; GUI читает через push (B9) |
| `RegistersStateAdapter`/`CameraStateAdapter`/`DisplayStateAdapter` | 0 прод-инстанцирований (Service/Recipe — с `state_proxy=None`, inert) | **мёртв** | — |
| `FrontendManager` + `FrontendRegistersBridge` + `set_send_callback`/`control_{channel}` | 0 в `multiprocess_prototype/` (инстанцируется только `frontend_module/application/process_attached_frontend.py:51` — **сам фреймворк, прототипом не вызывается**) | **мёртв (в v3)** | контракт ключей `register_name` ≠ `register` (HIGH-риск #2). Подтверждено: `grep process_attached_frontend|FrontendManager` по prototype = 0 |
| `ConfigStoreFromManager.subscribe/.set`, `Config.subscribe` | 0 прод (только `Config.get`) | **мёртв** | half-built (TODO Phase E) |
| `LoggerManager._route_via_router` | gated, доставка в никуда (нет процесса `logger`) | **мёртв-доставка** (B12) | enable-флаг + `_router_manager` нужны одновременно |
| `PreviewWindow._on_frame_received`/`subscribe` | 0 прод (инстанц. только в собств. `__main__` demo `preview_window.py:338`; `DisplaysTab.create` не передаёт router) | **мёртв** | нет продюсера |
| `SQLManager.execute_command` (db.query/execute/insert) | 0 прод-регистраций (`register_command('db.query',...)` нигде; tests + README) | **мёртв** | оставить library-API `query/execute` |
| `process_manager_proxy.replace_blueprint` (sync launch) | 0 прод (proxy в config только в тестах) | **мёртв (в v3)** | в prod — warning «proxy недоступен» |
| top-level `frontend/bridge.py` `DataReceiverBridge` | 0 (затенён `bridge/__init__.py:12` → `bridge_impl`) | **мёртв-дубль** | живой — `bridge_impl.py:14` |

---

## Расхождения с аудитом (COMMUNICATION_MAP / raw.json)

1. **`MessageAdapter.create_message` — уточнение, не противоречие.** §3.4 верно помечает символ как ссылающийся на несуществующее. Уточняю: метод `create_message` **отсутствует на классе `MessageAdapter`** вовсе; в `plugin_orchestrator.py:273,325` он вызывается в **dead-ветке `else`** (когда `_io is None`). Primary register-relay идёт через `_io.send_data` (жив). То есть B11-relay как механизм **жив**, а конкретно `create_message`-ветка — мертва. (Аудит это смешивал в одну строку.)

2. **`DeltaDispatcher._send_state_changed` — `type:"event"`, не `type:"system"`.** §1.3 описывает state-телеметрию верно (U1), но фактический билет несёт `type:"event"` + `queue_type:"system"` + `command:"state.changed"` (`delta_dispatcher.py:107-120`). Для P0.2 важно: целевой `MessageType` тут = `STATE` (диспатч идёт по `command`, не по `type`), при том что `type` в билете сейчас `"event"`. Это пример, где `type`-поле **не** соответствует целевому `MessageType` (см. риски).

3. **`FrontendManager` — подтверждено мёртв в v3, но в framework есть прод-конструктор.** §3.4 прав («не строится в v3»). Нюанс для P5: `process_attached_frontend.py:51` инстанцирует `FrontendManager` **внутри фреймворка** — этот модуль прототипом не импортируется (0 ссылок в `multiprocess_prototype/`), но при изоляции надо учесть и framework-self-reference.

4. **`register_broadcast_route` жив, `register_route`(single) мёртв — НЕ путать.** Аудит §3.4 относит к мёртвым «`register_route` (single), `register_channel_scenario`, `register_channel_handler`». Подтверждаю по отдельности: single `register_route` — мёртв; `register_broadcast_route` — **жив** (`frame_router_setup.py`), хотя его маршруты dormant. План это уже учитывает (P5.0: «`register_route`/`register_channel` — НЕ кандидаты»).

5. **Все 12 bypass'ов raw.json подтверждены на текущем коде** по строкам/символам. Сигнатуры совпадают с аудитом. Изменений после Фазы 1 `assigned_worker` в обходах **нет** (Фаза 2 PENDING).

---

## Риски / вопросы для P0.2

1. **`type`-поле ≠ целевой `MessageType` (ключевой риск маппинга).** Диспатч на приёме и резолв канала идут **по `command`**, когда он есть (`router_manager.py:295,601`), а `type` — вторичен. Несоответствия:
   - B9 state-fanout: `type:"event"`, но семантика — STATE (диспатч по `command="state.changed"`).
   - B4 heartbeat: `type:"system"` + `subtype:"heartbeat"` + `command:"heartbeat"` — тройная типизация, читается только `command`.
   - B8 state set/merge: `type:"command"`, command `state.*`.
   - B10 events: `type:"system_event"` (строка, не из enum `MessageType`).
   → P0.2 должен решить: маппить в канал **по `MessageType`** (как требует план), но текущие билеты не ставят `MessageType` консистентно. Нужна нормализация `type`/`command` → `MessageType` (фабрика билетов), иначе таблица `MESSAGE_TYPE_TO_CHANNEL` не сработает на живых сообщениях.

2. **Два поля адресации одновременно: `target` (скаляр) и `targets` (list).** Data-plane (B2/B3) и `send_to_process` используют **`target`** (скаляр) + кладут `targets` в fallback (`process_communication.py:205`). CommandSender/StateProxy/DeltaDispatcher используют **`targets:[...]`**. `_deliver_by_targets` читает только `targets`. → P0.2 address-helper должен принять оба; целевой контракт — `targets:list[str]` с dotted-адресом. Сейчас `targets` **нигде не dotted** (всегда плоское имя процесса) — иерархия `proc.worker` ещё не существует в данных (backward-совместимо).

3. **Поле `channel:"data"` у data-сообщений vestigial.** B2/B3 ставят `channel:"data"`, но доставка идёт по `target`+`queue_type` через `send_to_process` (не через `_resolve_channels`, т.к. `send_to_process` вообще минует `send`). Если P1 оживит `send`, явный `channel:"data"` начнёт резолвиться первым (приоритет 1 в `_resolve_channels`) — надо решить, удалять ли его из билета или регистрировать канал с именем `data`. **Конфликт:** `_deliver_by_targets` НЕ срабатывает, если `msg["channel"]` задан (`router_manager.py:230`) — значит при миграции data-plane на `router.send` придётся либо убрать `channel`, либо зарегистрировать реальный `data`-канал.

4. **Формат SHM-handle (Claim Check).** Координаты в `data`: `{shm_name (=slot), shm_index, shm_actual_name (вкл. PID на Windows), width, height}` + опц. `shm_owner` (`frame_shm_middleware.py:54-72,104`). Два читателя: `MemoryManager.read_images` (приоритет) и прямой `SharedMemory(name=shm_actual_name)` fallback (`router .../frame_shm_middleware.py:142`). P3.1 должен сохранить **оба** ключа (`shm_name`+`shm_actual_name`) при слиянии middleware — иначе GUI-fallback (другой OS-процесс) сломается.

5. **`queue_type` определяется в трёх местах с одинаковой, но раздублированной логикой** (`send_to_process:200`, `_deliver_by_targets:237`, `broadcast:232`): `system` для `command`, иначе `data`. При слиянии в address-aware канал — единое место выбора очереди.

6. **U1 `_deliver_by_targets` пропускает `target in ("all","broadcast")`** (`router_manager.py:241`) — а broadcast идёт отдельным путём (`queue_registry.broadcast_message`). P0.2/P1 должны решить, как broadcast выражается в address-модели (спец-адрес vs fan-out канал).

7. **fire-and-forget:** `state.get`/`get_subtree` (мёртвы) и `process.command.response` используют sync `router.send` (`state_proxy.py:495`) / correlation, но потребителя correlation_id нет. Вне scope транспорта (план относит в StateStore-подтверждение), но при оживлении `send` важно не сломать sync-ответ `state.get` если его решат оживить.

8. **`register_broadcast_route` (frame.camera_N) dormant, но ЖИВ как регистрация** — при введении `FrameChannel` (P3.1) надо снять эти неиспользуемые broadcast-маршруты, чтобы не плодить dormant-машинерию (HIGH-риск #1 аудита).

---

## Сводка покрытия

- Все **12 bypass'ов** из `router_audit.bypasses` пройдены и подтверждены по строкам (B1–B12).
- Для каждого живого отправляющего call-site указаны: фактические dict-ключи, `crosses_process`, целевой `MessageType`, целевой канал, объём миграции.
- Перепроверены **19 символов** мёртвого кода §3.4 + дополнительно `register_broadcast_route` (жив) и `MessageAdapter.create_message` (символ отсутствует).
- Приёмная половина (Таблица 2) — подтверждена как остающаяся каноническая.
