# Salvage digest — аудит коммуникаций

Карт: 13 · находок: 112

## Карты граней (каталог)

### envelope-field-mapping
- scope: in-process-and-cross-process
- relation_to_router: core-receive-hub-fallback-delivery-via-queue-registry-not-channel-routing
- layer_notes: framework (universal envelope) defines Message; prototype uses via MessageAdapter, CommandSender (hardcoded dict), build_command_message. Field routing is framework-universal; actual dispatch in prototype is minimal (no genuine channel routes except legacy state.changed workaround via queue_type fallback).
- components:
    - Message (IPC Value Object) (container) — multiprocess_framework/modules/message_module/core/message.py
    - MessageAdapter (contextual-factory) — multiprocess_framework/modules/message_module/adapters/message_adapter.py
    - RouterManager (send-receive-hub) — multiprocess_framework/modules/router_module/core/router_manager.py
    - DeltaDispatcher (state-producer) — multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py
    - command_envelopes (envelope-builder) — multiprocess_framework/modules/message_module/builders/command_envelopes.py
    - Addressing (hierarchical-routing) — multiprocess_framework/modules/message_module/addressing/address.py

### statestore-transport
- scope: in-process (state mutations) + cross-process (IPC via RouterManager queue_registry by targets)
- relation_to_router: Core: StateProxy/StateStoreManager use IRouter.send_async/send for IPC dispatch; StateProxy.on_state_changed registered via IRouter.register_message_handler('state.changed', ...) in each ProcessModule; DeltaDispatcher._send_state_changed sends to {subscriber}_system queue (U1-fallback delivery by RouterManager._deliver_by_targets)
- layer_notes: universal (framework): all 8 components are framework-level, reusable across projects. StateProxy/GuiStateProxy are client abstractions; StateStoreManager/DeltaDispatcher/SubscriptionManager/TreeStore are server abstractions. app-specific: bootstrap configuration (initial state, middleware, adapter setup) in multiprocess_prototype/backend/state/
- components:
    - StateProxy (client-side proxy (each ProcessModule) — sends/receives state mutations via IPC; caches subscribed paths; registers callbacks locally) — multiprocess_framework/modules/state_store_module/proxy/state_proxy.py
    - GuiStateProxy (Qt-safe subclass of StateProxy — routes callbacks to Qt main thread via QMetaObject.invokeMethod (QueuedConnection)) — multiprocess_framework/modules/state_store_module/proxy/gui_state_proxy.py
    - DeltaDispatcher (server-side IPC multiplexer — matches deltas to subscriptions, groups by subscriber (dedup), sends state.changed batches) — multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py
    - SubscriptionManager (subscription registry with glob pattern matching — thread-safe (RLock); matches Delta paths against patterns; excludes sources) — multiprocess_framework/modules/state_store_module/core/subscription_manager.py
    - StateStoreManager (server facade — registers 7 message handlers (state.set/.merge/.get/.subscribe/.unsubscribe/.unsubscribe_all) in RouterManager; orchestrates TreeStore + SubscriptionManager + DeltaDispatcher) — multiprocess_framework/modules/state_store_module/manager/state_store_manager.py
    - TreeStore (server-side hierarchical state tree — set/merge/get/delete produce Delta objects for DeltaDispatcher) — multiprocess_framework/modules/state_store_module/core/tree_store.py
    - Delta (immutable change unit — path, old_value, new_value, source, timestamp; serialized in state.changed IPC messages) — multiprocess_framework/modules/state_store_module/core/delta.py
    - IRouter (Protocol) (external dependency duck-type — defines register_message_handler(key, handler), send_async(msg), send(msg); implemented by RouterManager) — multiprocess_framework/modules/state_store_module/interfaces.py

### ipc-channel-map
- scope: mixed
- relation_to_router:
  "anchor (всё через RouterManager): _do_send/_resolve_channels/_deliver_by_targets/_select_queue_type/broadcast/receive/_route_to_worker/_resolve_pending; channel_dispatcher + message_dispatcher = ядро; AsyncSender/AsyncReceiver = фасад; queue_registry/QueueChannel = транспорт"

- layer_notes:
  "Framework (multiprocess_framework/modules): ядро RouterManager, каналы, очереди, диспетчеры — универсальное. Services/Plugins: используют send_to_process (через queue_registry) — app-specific. Prototype: frame_router_setup + GUI subscribe — Inspector-специфика"

- components:
    - RouterManager (Core Hub) (anchor:ядро маршрутизации) — multiprocess_framework/modules/router_module/core/router_manager.py
    - AsyncSender (endpoint:async_outgoing) — multiprocess_framework/modules/router_module/core/_sender.py
    - AsyncReceiver (endpoint:async_incoming) — multiprocess_framework/modules/router_module/core/_receiver.py
    - ProcessCommunication (adapter:process_interface) — multiprocess_framework/modules/process_module/communication/process_communication.py
    - QueueChannel (transport:multiprocess_queue) — multiprocess_framework/modules/router_module/channels/queue_channel.py
    - StateProxy (client:state_sync) — multiprocess_framework/modules/state_store_module/proxy/state_proxy.py
    - FrameRouterSetup (config:frame_fan_out) — multiprocess_prototype/backend/routing/frame_router_setup.py
    - PreviewWindow (subscriber:shm_frames) — multiprocess_prototype/frontend/widgets/displays/preview_window.py
    - ActionBus (dead:no_consumers) — multiprocess_framework/modules/actions_module/bus.py
    - CommandDispatcher (Domain Dispatch) (live:main_command_path) — multiprocess_prototype/adapters/dispatch/command_dispatcher.py

### request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request
- scope: cross-process (driver↔host TCP; ProcessModule↔ProcessManagerProcess queue; StateProxy↔StateStoreManager RouterManager)
- relation_to_router: RouterManager._pending_requests + _resolve_pending() + reply_to_request() are P0.5 request-response foundation. _pending_requests reacts in receive() on type='response' (line 503-507). reply_to_request() explicitly targets control-plane (queue_type='system') to avoid data-plane noise. StateProxy.subscribe() breaks the pattern: no request_id → no pending tracking → async ack without correlation guarantee
- layer_notes: Universal (framework candidate): P0.5 sync-request-response-over-async-transport (correlation_id, pending registry, timeout) is reusable. App-specific: ProcessManagerProcess._handle_process_command responder (CommandManager delegation, data unwrapping).
- components:
    - BackendDriver.request() (Initiator-side request-response over TCP socket. Assigns request_id, enqueues _Pending slot, blocks on event.wait(timeout). On _read_loop: demux by request_id → pending.response→event.set()) — backend_ctl/driver.py:109-135
    - _Pending slot (sync-response awaiter) (Threading synchronization primitive: threading.Event + response dict. Initiator blocks; reader sets when correlation matches) — backend_ctl/driver.py:27-34
    - RouterManager._pending_requests (Registry of awaiting request() calls: correlation_id → _PendingRequest. Zero-overhead when empty (hot-path guard). Filled on request(), resolved in receive() on type='response') — multiprocess_framework/modules/router_module/core/router_manager.py:115-121
    - RouterManager._resolve_pending() (Lookup correlation_id in pending registry; if found: pending.response←response, pending.event.set() → returns True (consumed by receive); else → False (message goes normal path)) — multiprocess_framework/modules/router_module/core/router_manager.py:396-408
    - RouterManager.request() [in-process] (Process-internal request-response: assign correlation_id, register _PendingRequest, send via _do_send, block on event.wait(timeout), extract result or error) — multiprocess_framework/modules/router_module/core/router_manager.py:341-394
    - RouterManager.reply_to_request() (Sender-side reply builder. Extracts correlation_id (priority: request_id > data.correlation_id). No-op if no correlation_id (fire-and-forget compat). Builds response with type='response', targets=[reply_target], queue_type='system' (control-plane), sends via send()) — multiprocess_framework/modules/router_module/core/router_manager.py:410-446
    - ProcessManagerProcess._handle_process_command() (Real responder: unwraps nested cmd from data, delegates to CommandManager, builds response with correlation_id + targets=[reply_target] + queue_type='system', sends via router_manager.send(). P0.5: not broadcast, targeted reply) — multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:828-918
    - StateProxy._send_sync() (Client-side IPC sync-send for state.subscribe/set/merge/get. Returns None on router=None or exception. Critical issue: no request_id field → cannot use request-response, falls back to implicit server ack) — multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:481-500
    - StateProxy.subscribe() handshake (Sends state.subscribe via _send_sync (NO request_id), expects response.status='ok' + sub_id. Response=None is silent (line 261-265 logs WARNING only but does NOT fail). Sub_id generated locally if server ack missing — fire-and-forget fallback. No pending-slot correlation, no guarantee handshake completed) — multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:218-294

### lifecycle-bridge
- scope: cross-process
- relation_to_router: ядро: RouterManager holds message_dispatcher; register_commands_with_router bridges CommandManager into it; heartbeat-обработчик регистрируется в ProcessManager's router; state.changed должен быть в тех же message_dispatcher-ах
- layer_notes: framework (universal constructor): ProcessLifecycle, ProcessModule.initialize, ProcessCommunication, ProcessHeartbeat, SystemThreads, RouterManager, GuiStateProxy (cross-process IPC layer). prototype (app-specific): CommandDispatcherOrchestrator (domain logic), Pipeline UI → commands (dependency violation risk: frontend should use bridge, not direct dispatch)
- components:
    - ProcessLifecycle.register_commands_with_router (Core Bridge: CommandManager → RouterManager.message_dispatcher registration) — multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py:104-132
    - ProcessModule.initialize (orchestrator) (Main lifecycle orchestrator — coordination hub for startup order) — multiprocess_framework/modules/process_module/core/process_module.py:124-180
    - ProcessModule._init_state_proxy (Auto-register state.changed handler in finally block (ADR-SS-006)) — multiprocess_framework/modules/process_module/core/process_module.py:262-275
    - ProcessModule.run (start lifecycle) (Secondary register_commands_with_router resync + heartbeat launch) — multiprocess_framework/modules/process_module/core/process_module.py:570-615
    - RouterManager.message_dispatcher (Central IPC message handler dispatcher (Dispatcher class)) — multiprocess_framework/modules/router_module/core/router_manager.py:94-100
    - SystemThreads._message_processing_loop (System worker thread consuming 'system' channel → message_dispatcher.dispatch()) — multiprocess_framework/modules/process_module/threads/system_threads.py:53-82
    - RouterManager.receive + dispatch (Sync poll channels + receive middleware + invoke message_dispatcher) — multiprocess_framework/modules/router_module/core/router_manager.py:457-526
    - ProcessHeartbeat (Background worker sending heartbeat messages to ProcessManager) — multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py:12-56
    - ProcessMonitor._register_heartbeat_handler (ProcessManager heartbeat handler registered in its own router) — multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:117-133
    - ProcessCommunication.register_router_channels (Register queue channels in router (targets_{qtype}, system_events)) — multiprocess_framework/modules/process_module/communication/process_communication.py:67-123
    - GuiStateProxy.on_state_changed (Qt-safe state.changed handler dispatching to main thread (not yet registered)) — multiprocess_framework/modules/state_store_module/proxy/gui_state_proxy.py:76-100
    - CommandDispatcherOrchestrator (LIVE domain-dispatch (Phase C): Project.apply → topology_repo.save → events) — multiprocess_prototype/adapters/dispatch/command_dispatcher.py:60-80

### prototype-communication-map
- scope: in-process: GuiProcess (main thread ↔ data_receiver worker via Qt QueuedConnection); cross-process: Router with shared queues (ProcessManager ↔ Camera ↔ Processor ↔ Display)
- relation_to_router: RouterManager is core: all IPC messages flow through send/receive/middleware; state.changed and heartbeat register via register_message_handler; broadcast routes (register_broadcast_route) fan out to {proc}_data/system channels
- layer_notes: Framework: RouterManager (router_module), GuiStateProxy (state_store_module), ProcessHeartbeat (process_module), ActionBus (actions_module); App-specific: GuiProcess, DataReceiverBridge, GuiStateBindings, TopologyBridge, ConnectionMap, domain action handlers
- components:
    - GuiProcess.data_receiver_loop (Worker thread receiving IPC frame/state messages from {proc}_data channel) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\process.py:117-181
    - DataReceiverBridge (Qt-thread-safe message dispatcher (worker→main via QueuedConnection)) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\bridge.py:14-74
    - GuiStateBindings (Glob-pattern reactive subscriptions for widget state updates) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\state\bindings.py:62-150
    - _StateDeltaEmitter (Qt slot for marshaling state.changed deltas to main thread) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\process.py:25-42
    - GuiStateProxy (StateStore client subscribing to state.changed (router message handler)) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\state_store_module\proxy\gui_state_proxy.py:34-100
    - TopologyBridge (GUI→Runtime IPC bridge (field_set, recipe_apply, topology mutations)) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\bridge\topology_bridge.py:1-120
    - ConnectionMap (Plugin→process mapping from topology YAML (routing table)) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\registers\connection_map.py:23-111
    - ActionBus (Domain action dispatch (apply/revert) with undo/redo) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\actions_module\bus.py:68-100
    - ProcessHeartbeat (System channel heartbeat sender (type:system, subtype:heartbeat)) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\process_module\heartbeat\process_heartbeat.py:12-80
    - RouterManager (Core multiprocess router (channels, dispatcher, middleware)) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\router_module\core\router_manager.py:43-241

### buses-action
- scope: in-process
- relation_to_router: parallel-door: action dispatch lives outside RouterManager (domain → adapters DI container); IPC uses RouterManager.send_command() only for live register updates (CommandSender → register_update handler); two buses parallel: domain-dispatch (LIVE) vs framework-ActionBus (vestigial)
- layer_notes: app-specific: CommandDispatcher routes domain-commands (Project.apply mutations) via typed EventBus (TopologyReplaced, PluginConfigChanged). Framework ActionBus retained as infra for future forms/system-settings domain migration (Phase G+). QtEventBus is universal Qt-aware EventBus wrapper (QueuedConnection marshaling for worker threads).
- components:
    - CommandDispatcherOrchestrator (LIVE) (core-dispatch) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\adapters\dispatch\command_dispatcher.py
    - EventBus (LIVE domain pub/sub) (domain-pubsub) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\domain\event_bus.py
    - QtEventBus (LIVE cross-thread wrapper) (qt-thread-safety) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\qt_event_bus.py
    - ActionBus (LEGACY - 0 direct consumers) (legacy-infra) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\actions_module\bus.py
    - ActionBus v2 factory (LEGACY - deprecated wrapper) (legacy-infra) — d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\actions\bus_factory.py

### pipeline-communication-boundaries
- scope: cross-process
- relation_to_router: ядро: all IPC routing through RouterManager; register_router_channels creates process-local + cross-process + local intra-process channels; receive(channel_types=[data]) filters to data queue only
- layer_notes: универсальное (framework): pipeline scaffold (generic_process, data_receiver, pipeline_executor, source_producer, frame_shm_middleware, inspector_manager, worker_manager) lives in multiprocess_framework; app-specific: recipe topology + plugin chain lives in multiprocess_prototype (editor + runtime)
- components:
    - ProcessCommunication.register_router_channels (channel_initialization) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/communication/process_communication.py
    - ProcessModule.initialize → _init_communication (bootstrap_entry_point) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/core/process_module.py
    - GenericProcess._init_data_pipeline (pipeline_topology_builder) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/generic/generic_process.py
    - DataReceiver.run_loop (data_ingress_worker) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/generic/data_receiver.py
    - PipelineExecutor.run_loop (data_processing_worker) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/generic/pipeline_executor.py
    - SourceProducer.run_loop (data_source_worker) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/generic/source_producer.py
    - FrameShmMiddleware (generic) (frame_transport_layer) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/generic/frame_shm_middleware.py
    - FrameShmMiddleware (router) (frame_transport_layer) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py
    - InspectorManager (fan_in_accumulator) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_framework/modules/process_module/generic/inspector_manager.py
    - PipelineTab (prototype UI) (recipe_editor) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py
    - WireStatus (telemetry) (wire_monitoring) — d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/pipeline/telemetry/wire_metrics_model.py

### Channel Communication Map
- scope: in-process (router_channels, dispatcher) + cross-process (queue_registry bypass + IMessageChannel transport) + GUI bridge (SocketChannel for backend_ctl)
- relation_to_router: RouterManager IS THE HUB: owns ChannelRegistry + channel_dispatcher (egress routing) + message_dispatcher (ingress type-dispatch). Channels are registered via register_channel(); routes via register_route/register_broadcast_route. But send-traffic: ~80-90% bypasses channel-routing via queue_registry.send_to_queue(process_name) (targets fallback U1). Channel-routed egress = EventManager.emit_event('system_events') only. Receive: universal — all messages polled via receive_message → _poll_all_channels → message_dispatcher
- layer_notes: app-specific (frame_router_setup) vs universal (channel_dispatcher, message_dispatcher, QueueChannel, SocketChannel). FieldRouting is framework-universal but adoption is app-specific (not in live prototype plugins). ActionBus is framework but DEAD in prototype flow.
- components:
    - channel_dispatcher (Dispatcher) (Channel routing registry — maps routing_key → handler → channel_name (name-returning pattern). Owned by RouterManager, fed by register_route/register_broadcast_route) — multiprocess_framework/modules/router_module/core/router_manager.py:869-921
    - message_dispatcher (Dispatcher) (Message-type dispatcher — routes incoming messages by 'type' field to handlers (command_manager, message_handlers, worker_handlers). Separate instance per process. Consulted AFTER channel resolution) — multiprocess_framework/modules/router_module/core/router_manager.py:298-317
    - FieldRouting (dataclass) (Typed descriptor for per-field routing: channel name, priority, transform, process_targets. Stored in FieldMeta.routing for schema-driven dispatch) — multiprocess_framework/modules/data_schema_module/core/field_routing.py:26-63
    - IMessageChannel interface (Contract for all message channels: send(msg), poll(timeout), start/stop_listening(). Stateless relative to routing — only transport I/O) — multiprocess_framework/modules/router_module/interfaces.py:172-228
    - QueueChannel (IMessageChannel) (multiprocessing.Queue wrapper. send() = queue.put; poll() = queue.get (non-blocking). Used for inter-process + intra-process (_local) queues) — multiprocess_framework/modules/router_module/channels/queue_channel.py:23-98
    - SocketChannel (IMessageChannel) (TCP server endpoint for external drivers (backend_ctl). Implements push-model with on_inbound callback for driver→system messages. Outbound via send()) — multiprocess_framework/modules/router_module/channels/socket_channel.py:34-263
    - ChannelRegistry (CRM dependency) (Thread-safe channel storage by name. Owned by ChannelRoutingManager, consulted by _resolve_channels() O(1) lookup) — multiprocess_framework/modules/channel_routing_module/core/channel_registry.py:24-94
    - ProcessCommunication.register_router_channels (Process initialization: creates QueueChannel names {process_name}_{qtype} for 'data'/'system'/'events' queues + {process_name}_local (threading.Queue). Registers system_events globally) — multiprocess_framework/modules/process_module/communication/process_communication.py:67-125
    - frame_router_setup (broadcast) (Dynamic broadcast fan-out for camera frames: register_broadcast_route('frame.camera_{id}', [processor, display, ...]) called at runtime) — multiprocess_prototype/backend/routing/frame_router_setup.py:26-98
    - ActionBus (legacy dead) (State mutation via Action with undo/redo. 0 prod execute() calls (only FormContext/RolesPanel, both guarded by form_ctx=None/_bus=None)) — multiprocess_framework/modules/actions_module/bus.py:68-95

### process_communication_boundary_map
- scope: cross-process and in-process: multiprocessing.Queue for cross-process, queue.Queue for intra-process local_channel
- relation_to_router: RouterManager is the exclusive hub: all send/receive/broadcast paths funnel through it; ProcessCommunication is a facade; message_dispatcher hooks incoming command dispatch; channel_dispatcher (name-returning handler) resolves routing keys to channel names for send pipeline
- layer_notes: Framework universal: Message (contracts), RouterManager (async send/receive, middleware, dispatch), ProcessCommunication (process-level api), QueueChannel (queue transport). Vestigial: 'data'/'system' channel names (recon #3, stripped at send_to_process line 210); local_channel (thread-safe intra-process, registered but not used by prototype)
- components:
    - ProcessCommunication (entry_point) — multiprocess_framework/modules/process_module/communication/process_communication.py
    - SystemThreads._message_processing_loop (message_processor_system_channel) — multiprocess_framework/modules/process_module/threads/system_threads.py
    - SystemThreads._handle_message (message_dispatcher_hook) — multiprocess_framework/modules/process_module/threads/system_threads.py
    - RouterManager (core_hub) — multiprocess_framework/modules/router_module/core/router_manager.py
    - RouterManager.receive (channel_polling) — multiprocess_framework/modules/router_module/core/router_manager.py
    - RouterManager._route_to_worker (worker_addressing) — multiprocess_framework/modules/router_module/core/router_manager.py
    - RouterManager._deliver_by_targets (addressing_fallback) — multiprocess_framework/modules/router_module/core/router_manager.py
    - QueueChannel (channel_transport) — multiprocess_framework/modules/router_module/channels/queue_channel.py
    - Message (message_contract) — multiprocess_framework/modules/message_module/core/message.py
    - ActionBus (domain_event_dead_code) — multiprocess_framework/modules/actions_module/bus.py
    - StateStoreProxy (state_subscription_gui_handshake_broken) — multiprocess_framework/modules/state_store_module/proxy/state_proxy.py

### comm-systems-census
- scope: cross-process
- relation_to_router: ядро (receive-hub, message_dispatcher, channel registry) + надстройка (AsyncSender buffering) + fallback-обход (send_message → queue_registry, _deliver_by_targets uses targets not channel-routing)
- layer_notes: framework (RouterManager, StateStore, EventBus, Dispatcher, ChannelRoutingManager, FrameShmMiddleware, MemoryManager, ProcessCommunication, Heartbeat) + prototype (CommandDispatcherOrchestrator, QtEventBus, GuiStateBindings, DataReceiverBridge, PreviewWindow, domain-events). ActionBus is framework but DEAD. FieldRouting/RouterSchemaAdapter framework but DEAD. SHM is canonical framework transport overlay on queue_registry.
- components:
    - RouterManager (IPC-хаб) (Receive-hub: AsyncReceiver polls all channels, message_dispatcher routes by command; Send facade with AsyncSender buffering; Channel registry; Message middleware pipeline) — multiprocess_framework/modules/router_module/core/router_manager.py:43-943
    - AsyncSender (Non-blocking buffered sender in PriorityQueue; enqueue(msg, priority) returns immediately; background worker thread) — multiprocess_framework/modules/router_module/core/_sender.py:31-138
    - AsyncReceiver (Polling listener thread; receive_fn() calls; callbacks invoked per-message; RLock-protected callback registry) — multiprocess_framework/modules/router_module/core/_receiver.py:21-156
    - StateStore (TreeStore) (Hierarchical dict with path-based access, atomic ops, returns Delta on change; root for all reactive state) — multiprocess_framework/modules/state_store_module/core/tree_store.py:60-489
    - EventBus (Pure Python synchronous typed pub/sub; subscribe(event_type, handler); publish snapshots handlers at register-time; RLock thread-safe) — multiprocess_prototype/domain/event_bus.py:78-151
    - QtEventBus (Qt-aware EventBus wrapper; cross-thread marshaling via Signal(object) QueuedConnection; domain-clean internal EventBus) — multiprocess_prototype/frontend/qt_event_bus.py:62-158
    - GuiStateBindings (GUI reactive subscriptions to StateStore paths via glob patterns; widget property setters; weakref auto-cleanup) — multiprocess_prototype/frontend/state/bindings.py:62-219
    - FrameShmMiddleware (router) (on_send: frame→SHM write, replace with coordinates; on_receive: SHM read from coordinates or direct SharedMemory open) — multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py:18-183
    - FrameShmMiddleware (process generic) (strip_and_write: lazy SHM allocation, round-robin slots, frame removal; restore_frame: MemoryManager or fallback SharedMemory) — multiprocess_framework/modules/process_module/generic/frame_shm_middleware.py:15-176
    - MemoryManager (SHM) (write_images/read_images API; SharedMemory buffer management; numpy payload serialization) — multiprocess_framework/modules/shared_resources_module/memory/interfaces.py:32-60
    - QueueRegistry (queue_registry) (Cross-process mp.Queue registry by process_name + queue_type; send_to_queue, broadcast_message) — multiprocess_framework/modules/shared_resources_module/queues/core/manager.py
    - ProcessCommunication (send_message(target, msg) → send_to_process → queue_registry.send_to_queue; broadcast_message fan-out) — multiprocess_framework/modules/process_module/communication/process_communication.py:279-281

### Services Communication Architecture: Channels/Commands/Subscriptions Map
- scope: in-process | cross-process (modbus_sink via plugin transport, SQL via local UoW/Repository interfaces)
- relation_to_router: CORE: ModbusChannel registers in RouterManager as transport-layer channel; commands routed via send(), inbound via poll(). UNIVERSAL: message envelope {command/op, data, channel} matches prototype FieldRouting expectations (control_pilot channel example). VESTIGIAL: SQL does NOT use RouterManager (execute_command called directly by consumers); Hikvision does NOT register channel (returns dict from produce(), no routing observed)
- layer_notes: ModbusChannel (Services/modbus/channels/) — universal, matches IMessageChannel contract exactly (send/poll/name/channel_type/start/close). ModbusPlugin/ModbusSinkPlugin/HikvisionPlugin (Services/*.plugin/) — app-specific adapters; plugins reuse framework lifecycle (configure/start/process/shutdown) via ProcessModulePlugin base. SQLManager (Services/sql/core/) — service-level, manager pattern (execute_command not via Router, direct dict dispatch). ALL follow framework conventions for logging injection (_log_info/_log_error callbacks) and status/error reporting (on_status/on_error callbacks into register/UI).
- components:
    - ModbusChannel (Universal transport layer implementing IMessageChannel interface; registers as 'modbus_N' channel in RouterManager) — Services/modbus/channels/modbus_channel.py
    - ModbusPlugin (IO-plugin bridging ModbusDevice → framework; registers channel in RouterManager on start(); implements poll-worker pattern for async telemetry) — Services/modbus/plugin/plugin.py
    - ModbusSinkPlugin (Output-sink plugin writing universal payload to Modbus holding registers; uses Services.modbus.ModbusDevice directly (ADR-DS-006 compliant)) — Plugins/sinks/modbus_sink/plugin.py
    - HikvisionCameraPlugin (Source-plugin for Hikvision cameras; produce() returns frame dict, no RouterManager integration observed) — Services/hikvision_camera/plugin/plugin.py
    - SQLManager (Database access manager; implements execute_command() for dict-at-boundary command dispatch (db.query/db.execute/db.insert)) — Services/sql/core/sql_manager.py

### queue-registry-addr-boundary
- scope: cross-process|in-process|mixed
- relation_to_router: core: RouterManager holds queue_registry ref (line 75); _deliver_by_targets (U1 fallback) calls qr.send_to_queue when channels don't resolve; register_worker_handler manages _worker_handlers dict for P2.2 hybrid control-plane
- layer_notes: framework (universal): addressing/split_address, IQueueRegistry, ProcessStateRegistry are reusable; app-specific (prototype): _route_to_worker, register_worker_handler patterns emerge as P2.2 hybrid; vestigial: channel 'data'/'system' strings in frames (recon #3)
- components:
    - IQueueRegistry (contract) (API boundary: send_to_queue, broadcast_message, register_process_queues, create_and_register_queues) — multiprocess_framework/modules/shared_resources_module/queues/interfaces.py
    - QueueRegistry (implementation) (manages Queue lifecycle via ProcessStateRegistry; send_to_queue(process_name, queue_type, message)) — multiprocess_framework/modules/shared_resources_module/queues/core/manager.py
    - ProcessStateRegistry (PSR) (single source of truth for Queue refs; stores in ProcessData._queues_dict; add_queue(process_name, queue_type, queue)) — multiprocess_framework/modules/shared_resources_module/state/process_state_registry.py
    - addressing module (P0.2) (hierarchical addressing: split_address, process_of, worker_of, is_broadcast; dotted-form process[.worker[.…]]) — multiprocess_framework/modules/message_module/addressing/address.py
    - RouterManager (core) (facade: holds queue_registry ref; _deliver_by_targets fallback; _route_to_worker(P2.2); register_worker_handler) — multiprocess_framework/modules/router_module/core/router_manager.py
    - ProcessCommunication (process-level: register_process_queues, broadcast, send_to_process via router.queue_registry) — multiprocess_framework/modules/process_module/communication/process_communication.py
    - SharedResourcesManager (SRM) (orchestrator: owns _queue_registry, _process_state_registry, passed to RouterManager) — multiprocess_framework/modules/shared_resources_module/core/shared_resources_manager.py

## Находки (дубли и тупики первыми)


### === duplicate ===

- **[high/mixed] Dual command dispatch paths (ActionBus vs CommandDispatcherOrchestrator)** `(ipc-channel-map)`
  - kind: redundancy
  - evidence: multiprocess_prototype/frontend/app.py:431-439 creates legacy ActionBus via create_action_bus(); multiprocess_prototype/frontend/app.py:557 sets app_services.commands = CommandDispatcherOrchestrator (from app_services_factory.py:177). Both registered in same app but different entry points. Legacy bus execution at multiprocess_prototype/frontend/tests/test_action_bus_v2.py:74 (bus.execute) vs domain path at multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:189 (self._services.commands.dispatch)
  - desc: Two independent mutation entry points coexist: ActionBus.execute() (legacy, lines 199-248 in bus.py) with handler registry and undo/redo, and CommandDispatcherOrchestrator.dispatch() (domain-driven, lines 90-152 in command_dispatcher.py) with Project.apply. App creates both but only CommandDispatcher is bound to domain command flow (pipeline/recipes tabs). ActionBus creates handlers for field_set, recipe_apply etc but these are never invoked in live path only in legacy tests and roles panel. CommandDispatcher supersedes ActionBus (line 422-427 in app.py explicitly notes ActionBus is 'legacy'). Two separate undo/redo stacks conflict with G.4.4 design (single undo via Ctrl+Z/Y).
  - dir: merge
- **[high/framework] Дубль FrameShmMiddleware идентичная SHM-логика в двух местах** `(pipeline-communication-boundaries)`
  - kind: redundancy
  - evidence: router_module/middleware + process_module/generic/frame_shm_middleware.py: identical SHM logic, router variant not used, generic variant on hot path
  - desc: 200+ lines duplicated SHM-logic in two variants. Only generic variant used on hot data path. Router variant registered but on_send never called, on_receive only in GUI when router available (dead path).
  - dir: merge
- **[high/framework] Dual message delivery paths: RouterManager targets fallback + queue_registry** `(comm-systems-census)`
  - kind: redundancy
  - evidence: router_manager.py:255-315 _deliver_by_targets() fallback; process_communication.py:279-281 send_message() calls router.send() then queue_registry; both reach send_to_queue().
  - desc: ProcessCommunication.send_message routes through RouterManager.send() which falls back to _deliver_by_targets() then queue_registry.send_to_queue(). Channel routing bypassed for practical use.
  - dir: merge
- **[high/mixed] register_update sent twice: domain-dispatch + PluginOrchestrator relay** `(comm-systems-census)`
  - kind: redundancy
  - evidence: app.py:524-540 GUI sends register_update; plugin_orchestrator.py:310-336 relays register_changed back. Relay dead-end.
  - desc: Double messaging: (1) GUI CommandSender sends register_update; (2) PluginOrchestrator relays register_changed. Relay has no consumer.
  - dir: fix
- **[medium/framework] send_to_process vs _deliver_by_targets — redundant routing paths** `(envelope-field-mapping)`
  - kind: redundancy
  - evidence: multiprocess_framework/modules/process_module/communication/process_communication.py:182-248

broadcast() method: if queue_registry available → direct broadcast_message(); else → router.send(targets=['all'])
Two implementation branches, same result.
  - desc: ProcessCommunication.broadcast() has conditional dual-path: legacy queue_registry.broadcast_message() OR router.send() fallback. Introduces confusion about which path is live and complicates RouterManager migration.
  - dir: merge
- **[medium/framework] DeltaDispatcher vs _select_queue_type() — two qtype rules** `(envelope-field-mapping)`
  - kind: redundancy
  - evidence: multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py:115: 'queue_type': 'system' hardcoded
vs RouterManager.py:243-253: _select_queue_type() canonical rule
No enforcement of sync.
  - desc: DeltaDispatcher hardcodes queue_type='system'; RouterManager provides canonical _select_queue_type() rule. Two sources of truth invite divergence.
  - dir: merge
- **[medium/services] message_dispatcher + CommandManager dual command routing (duplicate paths)** `(Channel Communication Map)`
  - kind: redundancy
  - evidence: process_module/core/process_module.py uses CommandManager.dispatcher for command routing. Plus router_manager.py:517-525 calls message_dispatcher.dispatch(msg, key_field='command'). Both dispatch on 'command' field.
  - desc: Command routing happens in two places: CommandManager (explicit control-plane) + message_dispatcher (unstructured). Not a bug (handlers idempotent) but violation of single-dispatch principle. Document boundary: CommandManager for commands, message_dispatcher for events.
  - dir: discuss
- **[medium/framework] ProcessManagerProcess._handle_process_command() builds response with redundant success+result in both envelope and data** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: redundancy
  - evidence: multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:894-907
    response = {
        "type": "response",
        "command": "process.command.response",
        "sender": self.name,
        "targets": [reply_target] if reply_target else [],
        "queue_type": "system",
        "request_id": correlation_id,
        "success": success,
        "result": result,
        "data": {
            "correlation_id": correlation_id,
            "success": success,
            "result": result,
        },
    }
  - desc: Response message wraps success/result in both top-level envelope (line 901-902) AND in nested data.* (line 904-906). This is redundant belt-and-suspenders: initiator (BackendDriver or RouterManager.request()) will extract from top-level envelope (request_id, success, result), while nested data.* is never read by standard path. If some legacy code reads from data.*, it's implicit coupling across protocol boundaries. Comment on line 889-892 explains intent ('P0.5: addressuem otpravitelyu') but duplication suggests uncertain contract.
  - dir: discuss
- **[medium/framework] Dual send paths: router.send() and ProcessCommunication.send_to_process() are identical** `(process_communication_boundary_ipc_audit)`
  - kind: redundancy
  - evidence: multiprocess_framework/modules/process_module/communication/process_communication.py:182-218 (send_to_process: builds msg with targets=[target], calls router.send). multiprocess_framework/modules/router_module/core/router_manager.py:186-240 (_do_send: tries _resolve_channels, then fallback _deliver_by_targets line 202). multiprocess_framework/modules/router_module/core/router_manager.py:255-315 (_deliver_by_targets: iterates targets, calls queue_registry.send_to_queue for each). Both paths end at queue_registry.send_to_queue(target, qtype). Comment line 184-190 acknowledges: 'odin put vmesto obkhoda routera' (one path instead of bypassing router).
  - desc: ProcessCommunication.send_to_process(target, msg) and RouterManager.send(msg with targets=[target]) are equivalent operations. send_to_process builds msg['targets']=[target] and calls router.send(). Inside router.send _do_send _resolve_channels (returns empty for targets-only) _deliver_by_targets (which iterates targets and calls queue_registry.send_to_queue). This is intentional fallback design, but the naming suggests two separate paths. Vestigial channel field is explicitly stripped (line 210-211) to prevent false 'channel not found' warnings. Abstraction is clear in code but unclear in API naming: send_to_process and send(targets=[...]) appear different but behave identically.
  - dir: discuss
- **[medium/framework] Дубль ring-buffer логики встроенный % vs RingBufferWriter** `(pipeline-communication-boundaries)`
  - kind: redundancy
  - evidence: generic/frame_shm_middleware.py:140-143 vs shared_resources_module/buffers/ring_buffer.py
  - desc: Two ring-buffer implementations: quick&dirty (3 lines) and full-featured class. Live pipeline uses quick version. Unused API complicates architecture.
  - dir: merge
- **[medium/mixed] Дубль DataReceiverBridge top-level vs impl затененэый** `(pipeline-communication-boundaries)`
  - kind: redundancy
  - evidence: bridge.py (dead, QueuedConnection) vs bridge_impl.py (alive, AutoConnection); __init__.py shadows top-level
  - desc: Two classes with same name. Shadowing at package level confuses IDE grep. Dead class wastes memory.
  - dir: delete
- **[medium/framework] State telemetry: ProcessMonitor._publish_state() + legacy process_full_status** `(comm-systems-census)`
  - kind: redundancy
  - evidence: process_monitor.py:177-190 _publish_state() live; line 534 process_full_status constructed but never published. Line 567 _publish_state active.
  - desc: Two state telemetry flows: (1) ProcessMonitor._publish_state() through StateStoreManager [live], (2) process_full_status dict in heartbeat [dead]. Single-source-of-truth violated.
  - dir: fix
- **[medium/services] Duplicate command dispatch paths: ModbusChannel.send() vs ModbusPlugin cmd_*() methods** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: redundancy
  - evidence: Services/modbus/channels/modbus_channel.py:102-140 (send/dispatch to modbus commands) AND Services/modbus/plugin/plugin.py:244-292 (cmd_connect, cmd_disconnect, cmd_read_registers, cmd_write_register, cmd_get_status)
  - desc: Two parallel command paths exist for Modbus operations: (1) ModbusChannel.send(message) implements _dispatch() with full command logic (read/write/connect/disconnect/status); (2) ModbusPlugin.cmd_*() methods duplicate the same operations independently. Both are wired separately: ModbusChannel gets commands via RouterManager.send(), ModbusPlugin via commands dict registration. When plugin is in use without channel registration, cmd_* methods execute; when channel is registered, send() also handles commands. This creates two sources of truth for the same business logic.
  - dir: merge
- **[low/framework] register_commands_with_router() called twice** `(lifecycle-bridge)`
  - kind: redundancy
  - evidence: multiprocess_framework/modules/process_module/core/process_module.py:155 + 607; ProcessLifecycle.register_commands_with_router() invoked in initialize() (line 155) and again in run() (line 607)
  - desc: ProcessModule.initialize() calls register_commands_with_router() at line 155, then run() calls it again at line 607. This is intentional — builtin commands (worker.*, wire.*, introspect.*) are registered AFTER initialize() finishes. The implementation is idempotent (register_message_handler replaces by key), but the pattern creates visual redundancy and doubles traversal of command_manager.get_commands().
  - dir: discuss
- **[low/framework] Two register_message_handler invocations for 'state.changed'** `(lifecycle-bridge)`
  - kind: redundancy
  - evidence: ProcessModule._init_state_proxy() at line 271 + GuiProcess._init_application_threads() at line 91; both call router_manager.register_message_handler('state.changed', handler). GuiProcess explicitly avoids _init_state_proxy by not passing state_proxy to __init__.
  - desc: ProcessModule._init_state_proxy() provides auto-registration of state_proxy.on_state_changed if state_proxy is passed to constructor. GuiProcess bypasses this by manually registering in _init_application_threads(). This creates two independent paths for the same operation. GuiProcess's explicit registration is intentional (to use GuiStateProxy with Qt signal emitter), but the pattern creates semantic ambiguity: which hook should be used?
  - dir: discuss

### === dead-end ===

- **[high/framework] ActionBus.execute() — zero consumers, mute feature** `(envelope-field-mapping)`
  - kind: redundancy
  - evidence: multiprocess_framework/modules/actions_module/bus.py:199-282

bus.execute(action) → handler.apply(action, self._rm) — 0 wired handlers detected. Grep 'bus.execute' returns only bus.py/tests; no registrations in frontend_module or prototype.
  - desc: ActionBus (undo/redo dispatcher) fully implemented (execute/undo/redo/record with pre-hooks, post-callbacks, persistence). However, zero producers call execute() in live flow. Feature advertised but invisible to consumers.
  - dir: discuss
- **[high/framework] GuiStateProxy.subscribe() — silent callback drop on server rejection** `(envelope-field-mapping)`
  - kind: silent-drop
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:259-294

if response is None or response.get('status')!='ok':
    self._log_warning(...)
# BUT: callback registered anyway despite warnings:
self._callbacks[local_sub_id] = [callback]
return local_sub_id
  - desc: StateProxy registers callback locally even when server subscription fails. on_state_changed() handler (GuiProcess:91) receives messages but deltas not filtered per pattern (silent fallback line 426-428). Root: subscribe() logs warning but returns sub_id regardless, obscuring failure.
  - dir: fix
- **[high/prototype] GuiStateProxy handler — manual registration required** `(envelope-field-mapping)`
  - kind: missing
  - evidence: multiprocess_framework/modules/process_module/core/process_module.py:271: framework auto-registers state_proxy handler
BUT multiprocess_prototype/frontend/process.py:91: GuiProcess manually registers, sets self.state_proxy=None to block framework
  - desc: GuiProcess manually registers GuiStateProxy (Qt-safe) handler to avoid double registration via framework _init_state_proxy(). Complicates onboarding: new GUI processes must remember hand registration or miss state updates.
  - dir: fix
- **[high/prototype] ActionBus: zero producers in production code** `(lifecycle-bridge)`
  - kind: vestigial
  - evidence: multiprocess_prototype/frontend/app.py:433; ActionBus created as _legacy_action_bus but never stored or used. Line 428-429 comment: 'G.5.3: no direct consumers'. Used only in tests and deprecated form-binding code paths.
  - desc: ActionBus is instantiated in GuiApplication._init_legacy_domain_infra() at line 433-439 but has zero consumers in production code. Created as infrastructure for legacy domain migrations (forms binding, ROLE_UPDATE, system-settings), but all handlers point to deprecated paths. Phase G.4.1 moved undo/redo to CommandDispatcherOrchestrator (domain-based snapshot history). The bus is retained for backward-compat but will silently drop any execute() calls.
  - dir: discuss
- **[high/framework] ActionBus.execute() — zero production callsites (dead-end)** `(Channel Communication Map)`
  - kind: silent-drop
  - evidence: multiprocess_framework/modules/actions_module/bus.py:199-282 defines execute(), but multiprocess_prototype searches reveal 0 execute() calls in live code paths. Only 5 test files + RolesPanel.self._bus guarded by form_ctx=None (roles_panel.py:49,111-112).
  - desc: ActionBus implements undo/redo plumbing (coalescing, stacks, pre/post hooks, audit callbacks) but consumer FormContext never instantiated with non-None bus. Framework provides full infrastructure but unused in prototype.
  - dir: discuss
- **[high/framework] StateStore GUI subscription — register_message_handler never wired (dead-end)** `(Channel Communication Map)`
  - kind: missing
  - evidence: state_store_module/proxy/gui_state_proxy.py:76-100 defines on_state_changed(msg). Documentation (line 21) shows wiring pattern: router.register_message_handler('state.changed', proxy.on_state_changed). Grep returns 0 matches for this registration in prototype.
  - desc: GuiStateProxy is framework abstraction for Qt-safe state.changed message handling (thread-safe signal emit). But wiring missing: GuiProcess never calls register_message_handler, so state updates arrive via receive() but no handler routes them to on_state_changed → signal → main thread. State deltas invisible to GUI.
  - dir: fix
- **[high/services] RolesPanel receives bus=None; ROLE_UPDATE action never executes** `(buses-action)`
  - kind: silent-drop
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\widgets\tabs\settings\administration\roles_panel.py:46-56

def __init__(
    self,
    auth: "AuthContext | None",
    bus: "ActionBus | None",
    parent: QWidget | None = None,
) -> None:
    ...
    self._bus: "ActionBus | None" = bus

And roles_panel.py:196-206:

def _on_permissions_changed(
    self, role_name: str, old_perms: list[str], new_perms: list[str]
) -> None:
    if self._bus is None:
        return
    ...
    self._bus.execute(action)
  - desc: RolesPanel is designed to accept an ActionBus and emit ROLE_UPDATE actions when permission matrix is modified (line 206). However, when RolesPanel is instantiated by TabFactory, no bus is provided. The bus parameter defaults to None, and when permissions change, the _on_permissions_changed handler silently returns (line 200-201) without executing. This creates a handshake break: UI emits signal, bus is missing, mutations silently dropped. Users see no error or feedback that their role edits are not being recorded.
  - dir: fix
- **[high/framework] ActionBus.execute() unreachable from production code (0 call sites in prototype)** `(prototype-communication-map)`
  - kind: missing
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\app.py:433 creates _legacy_action_bus via create_action_bus().

GREP search shows bus.execute() only in: test_action_bus_v2.py, test_phase*.py (integration tests), test_pre_execute_hook.py (setup), ONE production site: multiprocess_prototype\frontend\widgets\tabs\administration\roles_panel.py:206.

BUT roles_panel is optional admin feature, not core pipeline. Core flow: FormContext.write -> domain CommandDispatcher (not ActionBus) or IPC send_field_set. See app.py:428-439: 'this legacy bus NO LONGER manages app undo'. See docs/COMMUNICATION_MAP.md line 62: 'ActionBus (dead: 0 prod-execute calls)'.
  - desc: Framework ActionBus is infrastructure-only: exists, initialized, handlers registered, but bus.execute() is never called in production except for roles administration panel (optional feature outside core pipeline). Global undo/redo was migrated to domain CommandDispatcher (window.set_undo_controller). Forms use domain-dispatch or direct IPC, not ActionBus. Bus remains as retained-but-unused infra for potential future domain migrations.
  - dir: discuss
- **[high/services] StateProxy.subscribe() missing request_id: no correlation tracking, handshake not guaranteed** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: silent-drop
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:243-253
    msg = {
        "type": "command",
        "sender": self._process_name,
        "targets": [self._server_target],
        "command": "state.subscribe",
        "data": {
            "pattern": pattern,
            "subscriber": self._process_name,
            "exclude_sources": exclude_sources,
        },
    }  <- NO request_id field, breaks RouterManager._resolve_pending() pattern
  - desc: StateProxy.subscribe() sends state.subscribe command but does NOT include request_id in message envelope (neither top-level nor in data.*). When _send_sync(msg) calls router.send(msg), the message goes to RouterManager but has no correlation ID. RouterManager._extract_correlation_id(msg) will fail, so even if StateStoreManager returns type='response', it will NOT match any pending slot in _resolve_pending(). Response travels normal path instead of correlating back. If response arrives before subscribe() caller examines status, callback wiring is incomplete -- subscription exists locally (line 287) but server handshake is uncorrelated.
  - dir: fix
- **[high/framework] ActionBus handlers never registered in prototype** `(process_communication_boundary_ipc_audit)`
  - kind: missing
  - evidence: multiprocess_framework/modules/actions_module/bus.py:110-117 (register_handler method). multiprocess_framework/modules/actions_module/bus.py:228-234 (execute checks if handler exists; logs warning and returns False if not found). ActionBus._handlers dict is always empty at runtime in prototype; create_action_bus factory (bus_factory.py:31-97) registers handlers but is never instantiated in prototype. Zero external consumers.
  - desc: ActionBus.execute() requires handler registration (bus.py line 228); if handler not found, returns False with warning. But prototype never calls create_action_bus, so _handlers remains empty. ActionBus capability (undo/redo/coalescing/pre-execute-hook/audit-middleware) is sound but unused. Framework provides two parallel command-execution engines: ActionBus (mute in prototype) and domain CommandDispatcher (live). Decision COMMUNICATION_MAP.md:2266 marked ActionBus for removal.
  - dir: discuss
- **[high/framework] StateStoreProxy.subscribe() handshake broken  callback never invoked** `(process_communication_boundary_ipc_audit)`
  - kind: silent-drop
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:259-280. If server response is None or status != 'ok', warning logged (lines 262-271). BUT callback IS still registered locally (line 287) with original local_sub_id. When server later sends state.changed, on_state_changed handler is invoked (line 323), updates cache (line 340), calls callback (line 341). However, server never subscribed (subscription failed), so no deltas arrive; callback fires only on stale local data.
  - desc: StateProxy.subscribe() silently succeeds even if server handshake fails. When server response=None or status!=ok, the warning explains 'server subscription not created' (line 263-265, 269-270), but client callback is registered anyway (line 287). This creates dangerous asymmetry: client believes subscription is active, invokes callback, updates cache from stale data. Server never sends state.changed updates because subscription failed silently. Callback appears to work (is invoked from cache) but receives no server updates. Fix: only register callback if handshake succeeds (response.status=='ok' AND server_sub_id exists), else raise or return error.
  - dir: fix
- **[high/framework] Тупик StateProxy.subscribe() handshake not registered** `(pipeline-communication-boundaries)`
  - kind: missing
  - evidence: state_proxy.py:247 sends 'state.subscribe', waits response; register_message_handlers never called in orchestrator.py:50
  - desc: Full path: StateProxy -> RouterManager.send -> queue_registry -> StateStoreManager.handle_state_subscribe. But message_handlers not registered in router. They exist but code never calls register_message_handlers (orchestrator only calls register_commands). Subscription sent (response=None WARNING), GUI gets no state.changed deltas.
  - dir: fix
- **[high/prototype] PreviewWindow broadcast route subscribed but no producer** `(comm-systems-census)`
  - kind: redundancy
  - evidence: preview_window.py:116-157 subscribe registers route; _on_frame_received() never invoked; Phase 4 placeholder, no frame producer.
  - desc: PreviewWindow subscribes display.* route but no code populates SHM or sends frames. Handshake incomplete: subscription registered, producer missing, window waits forever.
  - dir: discuss
- **[high/prototype] ActionBus execute() is dead-end: no consumers in production paths, replaced by domain_dispatch** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/actions_module/bus.py:68 (ActionBus class definition) and multiprocess_prototype/frontend/tests/test_action_bus_v2.py (0 real consumers in frontend logic, only tests) vs multiprocess_prototype/adapters/dispatch/command_dispatcher.py:90 (CommandDispatcherOrchestrator.dispatch() is the REAL dispatcher)
  - desc: ActionBus.execute(action) is defined and tested but has ZERO production consumers in the pipeline. All mutable operations in the pipeline tab go through domain_dispatch (CommandDispatcherOrchestrator.dispatch), which implements snapshot-based undo/redo that mirrors ActionBus semantics but works at domain level, not register level. ActionBus lives only in tests (test_action_bus_v2.py, test_phase12_integration.py) and legacy settings sections. The comment at multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py:6 explicitly states 'G.4.2: ActionBus bridge removed; undo/redo through services.commands (domain dispatch).' This is a framework capability that the prototype has superseded.
  - dir: discuss
- **[medium/framework] system_events channel has 0 consumers** `(ipc-channel-map)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/process_module/communication/process_communication.py:111-122 registers 'system_events' channel via QueueChannel; multiprocess_framework/modules/shared_resources_module/events/core/manager.py:131-138 sends type=system_event to targets=['ProcessManager'] on system_events channel; no message_handler registered for 'system_event' command; no router.receive(channel_types=['system_events']) call found.
  - desc: EventManager.emit_event() publishes via 'system_events' channel (manager.py line 131-138). Channel is registered in framework routing, but no consumer subscribes to it. ProcessManager has no handler for type='system_event'. In-process local queue fallback exists (line 143-146) but IPC path is dead. Framework infrastructure awaiting first consumer.
  - dir: fix
- **[medium/framework] _legacy_action_bus created but completely unbound in production** `(buses-action)`
  - kind: vestigial
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\app.py:433-439

_legacy_action_bus = create_action_bus(
    registers_manager,
    topology_store,
    topology_bridge=topology_bridge,
    auth_state=_auth_state,
    auth_manager=_auth_manager,
)

Variable is assigned but never referenced again (grep confirms 0 consumers).
  - desc: ActionBus is instantiated in run_gui() with full configuration (handlers for FIELD_SET, RECIPE_APPLY, PROCESS_ADD, PROCESS_REMOVE, WIRE_ADD, WIRE_REMOVE, NODE_MOVE, PreAuthGuard, AuditMiddleware, RoleUpdateHandler). However, the instance is stored in a local variable and never passed to any downstream consumer (not to TabFactory, not to AppServices, not to RuntimeDeps). Only RolesPanel.execute(ROLE_UPDATE) could use it if the bus were bound, but RolesPanel receives bus=None in production (TabFactory does not pass bus parameter). The comment at line 429 describes this as "retained infra" but the bus is inaccessible to any code.
  - dir: discuss
- **[medium/mixed] Тупик ActionBus dead 0 prod consumers** `(pipeline-communication-boundaries)`
  - kind: vestigial
  - evidence: app.py:433 creates _legacy_action_bus, never passed to clients; RolesPanel(None) guard blocks execute(); domain-commands use ProjectCommand
  - desc: ActionBus v2 fully functional but not integrated. Created in app.py but not distributed to UI widgets. Domain uses separate ProjectCommand path. Dead Phase 12-13 structures.
  - dir: discuss
- **[medium/framework] ActionBus.execute() unreachable in production** `(comm-systems-census)`
  - kind: redundancy
  - evidence: bus.py:199-282 implementation; form_context.py:90 only production call; command_dispatcher.py Phase C replaced it; tests only elsewhere.
  - desc: ActionBus undo/redo replaced by CommandDispatcherOrchestrator. FormContext.write() still uses for field edits; main command dispatch bypasses it.
  - dir: discuss
- **[medium/framework] FieldRouting/RouterSchemaAdapter unused in production** `(comm-systems-census)`
  - kind: tight-coupling
  - evidence: schema_adapter.py:37-130 RouterSchemaAdapter full implementation; only test usage. FieldRouting extracted via connection_map not schema_adapter.
  - desc: RouterSchemaAdapter maps FieldRouting to channel routes but never instantiated in runtime. RouterManager.channel_dispatcher empty except manual registration.
  - dir: discuss
- **[medium/services] StateStore GUI subscription handshake incomplete: state_proxy.set() in ModbusPlugin._push_state() returns silently without confirmation** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: leaky-abstraction
  - evidence: Services/modbus/plugin/plugin.py:194-202 (_push_state calls proxy.set('modbus/{unit_id}/values') but catches all exceptions silently with pass) AND multiprocess_prototype/frontend/process.py:95-101 (GuiProcess subscribes via exclude_self=True, callback is no-op)
  - desc: ModbusPlugin attempts to push live telemetry to GUI StateStore via state_proxy.set() at line 200. However: (1) state_proxy reference is obtained from ctx via getattr with None fallback, never confirmed to exist or be initialized; (2) set() call is wrapped in bare except Exception pass, meaning delivery failures are silent; (3) GuiProcess subscribes on 'processes.**' which would NOT match 'modbus/{unit_id}/values' path pattern (different branch). The subscription callback is intentionally a no-op lambda, with real delivery delegated to emitter. This creates the appearance of live state flow but the handshake between ModbusPlugin._push_state and GUI state-binding never completes.
  - dir: fix
- **[low/framework] Тупик dispatch_module (CHAIN_MATCH, scenarios) dead 0 calls** `(pipeline-communication-boundaries)`
  - kind: vestigial
  - evidence: dispatch_module: 0 prod registrations, only tests. Real routing always EXACT_MATCH. register_scenario dead.
  - desc: Historical baggage from Phase 8 rich routing design. Unused pattern/chain strategies. Real pipeline uses linear plugin.process() chain, not DAG dispatch. Complicates codebase.
  - dir: discuss
- **[low/framework] Dispatcher PATTERN/FALLBACK/CHAIN strategies unused** `(comm-systems-census)`
  - kind: tight-coupling
  - evidence: dispatcher.py:101-113 DispatchStrategy enum 4 strategies; only EXACT_MATCH in production; others in tests only.
  - desc: 4 dispatch strategies implemented but only EXACT_MATCH used. PATTERN, FALLBACK, CHAIN untouched in live flow.
  - dir: discuss

### === active-bug ===

- **[high/framework] Subscription handshake incomplete: sub_id assigned locally despite server rejection** `(statestore-transport)`
  - kind: leaky-abstraction
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:255-294 — StateProxy.subscribe() accepts error responses (response is None, status != ok, missing sub_id) yet still registers callback locally and returns sub_id. See lines 262-280 where warnings are logged but execution continues to line 287.
  - desc: When StateProxy.subscribe() receives an error response from StateStoreManager (lines 260-280), it logs a warning but then unconditionally registers the callback locally (line 287) and returns a sub_id to the caller. This creates a false contract: the caller believes the subscription is active and callback will fire, but the server never created the subscription. Delta messages never arrive. Callers like RecipeStateAdapter (backend/state/adapters/recipe_adapter.py:73-76) receive sub_id and trust it.
  - dir: fix
- **[high/mixed] No error recovery on subscription failure in state adapters** `(statestore-transport)`
  - kind: silent-drop
  - evidence: multiprocess_prototype/backend/state/adapters/recipe_adapter.py:73-77 — RecipeStateAdapter._subscribe_all() calls proxy.subscribe() with no error checking. Due to SS-T001, if server rejects subscription, sub_id is still returned and stored in _sub_ids (line 77). Callback _on_state_active_changed will never fire. No exception, no logging at adapter level.
  - desc: State adapters (recipe, display, service, camera, registers) trust subscribe() creates working subscription. Due to SS-T001 bug, rejection silently succeeds. Callbacks never fire. Domain state diverges from StateStore without user-visible error or logging in adapter code. User sees stale UI state.
  - dir: fix
- **[high/framework] request() — blocks without thread isolation guarantee** `(envelope-field-mapping)`
  - kind: tight-coupling
  - evidence: multiprocess_framework/modules/router_manager.py:346-353

DOCS: 'ВАЖНО: нельзя вызывать из потока receive()/start_listening() — дедлок'
BUT: No runtime guard — if message handler calls request(), deadlock to timeout.
  - desc: Documentation warns: cannot call request() from receive thread. No assertion prevents it. If handler inadvertently calls request(), deadlock ensues. Constraint only in docstring.
  - dir: fix
- **[high/framework] GUI StateProxy.on_state_changed handler registered but StateStoreManager never sends state.changed** `(ipc-channel-map)`
  - kind: leaky-abstraction
  - evidence: multiprocess_prototype/frontend/process.py:91 registers router.register_message_handler('state.changed', self._gui_state_proxy.on_state_changed); multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:260-294 shows StateProxy.subscribe() sends command='state.subscribe' to StateStoreManager but StateStoreManager has no handler to process this command or send state.changed responses.
  - desc: IPC handshake incomplete: GUI subscribes expecting state.changed callbacks, server never sends them. StateProxy.subscribe() masks error with warning log (state_proxy.py:262-266), causing silent data loss. GUI state bindings for processes.X.state.* never update. Handler in router is ready but dead endpoint.
  - dir: fix
- **[high/prototype] GuiStateProxy._state_emitter callback never triggered due to missing StateStoreManager implementation** `(ipc-channel-map)`
  - kind: missing
  - evidence: multiprocess_prototype/frontend/process.py:78-96 creates _StateDeltaEmitter and registers handler, but StateStoreManager.process_command() has no implementation to send state.changed messages. Subscription sends empty callback (comment line 92-94) expecting emitter to receive via message_handler.
  - desc: State subscription chain incomplete. GUI subscribes expecting live process telemetry (processes.X.state.*) to flow through emitter to GUI state bindings via bridge. But StateStoreManager doesn't implement state.subscribe command handler, so no callbacks sent. Emitter._on_state_deltas() never invoked.
  - dir: fix
- **[high/services] RolesPanel signal-to-bus connection broken due to missing _bus parameter** `(buses-action)`
  - kind: silent-drop
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\widgets\tabs\settings\administration\roles_panel.py:110-112

if self._can_edit and self._bus is not None:
    self._matrix.permissions_changed.connect(self._on_permissions_changed)

When _bus is None (line 111 condition fails), signal is never connected.
  - desc: RolesPanel connects PermissionMatrix.permissions_changed signal to _on_permissions_changed only if _bus is not None. Since _bus is None in production (BA-2), the signal is never connected. When a user with roles.edit permission changes role permissions, the signal fires but there is no handler (signal not connected). User edits are lost silently. Combined with BA-2, this forms a complete handshake break: UI sends signal, no handler exists, user action is lost.
  - dir: fix
- **[high/framework] state.changed subscription incomplete handshake: subscribe() succeeds but register_broadcast_route() never called** `(prototype-communication-map)`
  - kind: leaky-abstraction
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\process.py:96 and d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\state_store_module\manager\delta_dispatcher.py:98-127

GuiProcess calls proxy.subscribe('processes.**', lambda _deltas: None) which:
1. Sends state.subscribe IPC to ProcessManager (succeeds) -> server creates subscription
2. BUT: NEVER calls router.register_broadcast_route('state.changed', ['{gui}_system'])

Result: DeltaDispatcher._send_state_changed() routes messages via queue_type="system" (line 115) and targets=[subscriber] (line 110), sending to {gui}_system queue. BUT the GUI is opaque to the framework -- the real question is: what CONSUMES state.changed from {gui}_system?

ANSWER: GuiProcess._data_receiver_loop() polls ONLY channel_types=['data'] (line 131), NOT 'system'. The message sits in {gui}_system, undelivered. The handshake is incomplete: publish-side says targets=['gui']->queue_type='system', but subscribe-side is deaf to 'system' -- it only hears 'data'.
  - desc: GuiStateProxy.subscribe('processes.**') returns success to caller, creating server-side subscription. Server sends state.changed to {gui}_system queue with queue_type='system' (per delta_dispatcher.py:115). But GuiProcess._data_receiver_loop() only polls channel_types=['data'] (process.py:131), ignoring 'system'. No register_broadcast_route() call establishes the reverse path. Protocol: subscribe=fire-and-forget (no ack required), but the actual delivery has a listening gap.
  - dir: fix
- **[high/services] GuiProcess._data_receiver_loop() hardcodes channel_types=['data'], missing 'system' for state.changed** `(prototype-communication-map)`
  - kind: tight-coupling
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\process.py:131

Line 131: msgs = self.router_manager.receive(timeout=0.1, channel_types=['data'], return_messages=False)

Receive loop ONLY polls 'data' channels ({gui}_data). But state.changed messages queued to 'system' channels ({gui}_system, per delta_dispatcher.py:115). Conflict: publish to system, consume from data.
  - desc: GuiProcess data_receiver_loop filters receive() to channel_types=['data'] only, ignoring 'system' channel. StateStore publishes state.changed with queue_type='system', sending to {gui}_system queue. Messages arrive in wrong queue -- never polled by receiver.
  - dir: fix
- **[high/services] StateProxy._send_sync() silently returns None on router.send() error, subscribe() falls back to local callback** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: silent-drop
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:481-500
    def _send_sync(self, msg: dict) -> dict | None:
        if self._router is None:
            return None
        try:
            return self._router.send(msg)  <- Exception -> except catches, returns None (line 496)
        except Exception as exc:
            self._log_error(...)
            return None

Combined with subscribe() line 261-265:
    if response is None:  <- silent drop
        self._log_warning(...)
    # Then line 287: callback registered anyway locally
  - desc: StateProxy._send_sync() catches ALL exceptions from router.send() and returns None. subscribe() treats None response as 'server didn't confirm' and logs WARNING (line 262-265) but CONTINUES -- it registers the callback locally (line 287) anyway. This creates asymmetry: (1) Client thinks subscription is local-only ('servernaya podpiska ne sozdana') but (2) If network recovers, StateStoreManager may have created the subscription during the error -- callbacks fire unexpectedly. Error is not propagated; caller cannot distinguish 'network error' from 'server rejected'. (3) On timeout from router.request() timing out -> None is indistinguishable from 'handler not implemented'.
  - dir: fix
- **[high/services] StateProxy.subscribe() registers local callback before server confirmation, success paths diverge** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: silent-drop
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:259-294
    if self._router is not None:
        response = self._send_sync(msg)
        if response is None:
            self._log_warning(...)
        elif response.get('status') != 'ok':
            self._log_warning(...)
        else:
            server_sub_id = response.get('sub_id')
            if server_sub_id:
                local_sub_id = server_sub_id
    # Lines 286-289: ALL paths register locally
    self._callbacks[local_sub_id] = [callback]
  - desc: subscribe() has three response paths: (1) response=None (network error), (2) response.status != 'ok' (server error), (3) response.status == 'ok' (success). In paths 1 and 2, subscription FAILS server-side but callback IS STILL registered (line 287). If StateStoreManager never creates server subscription, state.changed pushes will not trigger this callback -- callback fires only when local code calls it explicitly. Caller code cannot easily distinguish 'subscription pending' from 'subscription failed' because both return a sub_id. on_state_changed (line 323) will invoke callbacks for this sub_id even if server subscription doesn't exist, causing phantom updates if state changes originate locally (violate exclude_self).
  - dir: fix
- **[high/prototype] GuiStateBindings subscription overwritten immediately** `(comm-systems-census)`
  - kind: silent-drop
  - evidence: app.py:222 GuiStateBindings registers callback; line 257 overwrites with wrapper. bindings.py:76-83 init calls set_state_callback then app.py replaces.
  - desc: GuiStateBindings.__init__ registers _on_state_msg but app.py overwrites immediately. Works now but fragile callback slot design.
  - dir: fix
- **[high/prototype] GUI RegistersManager.set_field_value() missing IPC to worker** `(comm-systems-census)`
  - kind: missing
  - evidence: app.py:501-540 sends register_update via PluginConfigChanged event; manager.py:52 expects connection_map but no IPC sender wired to notify_observers.
  - desc: GUI field write should trigger register_update IPC but dispatch incomplete. Domain-path works (event hook); direct set_field_value() has no IPC sender. Worker never notified.
  - dir: fix
- **[medium/framework] Manual state.changed handler registration in GuiProcess defeats ADR-SS-006 auto-register** `(statestore-transport)`
  - kind: inconsistency
  - evidence: multiprocess_prototype/frontend/process.py:85-91 — GuiProcess.register_message_handler manually. multiprocess_framework/modules/process_module/core/process_module.py:262-279 — _init_state_proxy auto-registers only if self.state_proxy is set, but GuiProcess does NOT set it (line 88 comment: 'do not set self.state_proxy to avoid double registration via ADR-SS-006'). GenericProcessApp (generic_process_app.py:38-41) does same manual registration.
  - desc: ADR-SS-006 promises automatic handler registration when state_proxy passed to ProcessModule, but GuiProcess intentionally prevents this by not setting self.state_proxy. Instead it manually registers (line 91). This creates two registration paths: automatic (ProcessModule._init_state_proxy) and manual (GuiProcess). Developers must remember to call register_message_handler explicitly, defeating the 'auto' promise.
  - dir: fix
- **[medium/framework] Incomplete response validation in StateProxy.subscribe IPC roundtrip** `(statestore-transport)`
  - kind: missing
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:259-280 — After _send_sync() returns, code checks response.get('status') and response.get('sub_id') without validating response is dict. If router returns non-dict (e.g. None, int, or malformed object), response.get() may raise AttributeError or silently return None.
  - desc: Response validation incomplete. Code assumes response is dict with optional keys, but does not validate type. If RouterManager or middleware returns unexpected type, lines 267 or 273 will raise AttributeError during .get() call. Better: validate response type early with clear error message.
  - dir: fix
- **[medium/framework] GuiStateProxy._dispatch_via_qt silent fallback to worker-thread callback on error** `(statestore-transport)`
  - kind: inconsistency
  - evidence: multiprocess_framework/modules/state_store_module/proxy/gui_state_proxy.py:106-133 — If PySide6 import fails or invokeMethod() raises exception, code catches and calls _invoke_callbacks (lines 128, 133). This processes deltas in worker thread, violating promise of main-thread delivery (line 40).
  - desc: GuiStateProxy promises Qt thread-safety by routing callbacks to main thread via invokeMethod. But if PySide6 unavailable or invokeMethod fails, code silently falls back to same-thread direct callback. Callbacks execute in worker thread, not main thread as promised. Defeats thread-safety guarantee. No exception raised to alert developer.
  - dir: fix
- **[medium/framework] MESSAGE_TYPE_DEFAULTS.channel='queue' — non-existent channel** `(envelope-field-mapping)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/message_module/types/message_types.py:45-86

MESSAGE_TYPE_DEFAULTS = {MessageType.COMMAND: {'channel': 'queue', ...}}

RouterManager._resolve_channels():876 treats 'queue' as sentinel ('не реальный канал Router')
  - desc: Framework defaults Message.type to channel='queue' but no IMessageChannel('queue') registered. RouterManager skips it as sentinel, forcing fallback to dispatcher or targets. Vestigial from pre-Router era; confuses readers.
  - dir: discuss
- **[medium/framework] Sync send vs async send_async — inverted return semantics** `(envelope-field-mapping)`
  - kind: inconsistency
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:169-184

send_async() → None (cannot detect failure)
send() → Dict[status] (caller can check)
No contract on when to use which.
  - desc: send_async() returns None (fire-and-forget), send() returns result dict. Names self-document but contract opacity invites misuse. No enforcement or guidance on caller choice.
  - dir: discuss
- **[medium/framework] Two parallel dispatch buses: domain EventBus (live) vs framework ActionBus (legacy, vestigial)** `(buses-action)`
  - kind: redundancy
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\domain\event_bus.py (live EventBus used by CommandDispatcher, TopologyBridge, presenter)
vs
d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\actions_module\bus.py (legacy ActionBus with handlers for mutations)

CommandDispatcher publishes ProjectEvents to EventBus (line 131-133 in command_dispatcher.py); ActionBus handlers apply mutations via handler.apply(). Different entry points, overlapping concerns.
  - desc: Two event/action dispatch systems coexist: (1) Domain EventBus (pure Python, thread-safe RLock, typed events) used by CommandDispatcher -> TopologyReplaced, PluginConfigChanged published to subscribers (PipelinePresenter, TopologyBridge); (2) Framework ActionBus (undo/redo stacks, handler registry) with handlers for field mutations and topology changes. In production, domain path (dispatch -> EventBus.publish) is live, ActionBus path is dead (unbound). This creates confusion about the canonical dispatch path and makes the codebase harder to reason about (two overlapping mechanisms for the same concern).
  - dir: discuss
- **[medium/framework] GuiStateProxy.subscribe() succeeds locally even if server subscription fails (silent degradation)** `(prototype-communication-map)`
  - kind: silent-drop
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\state_store_module\proxy\state_proxy.py:259-294

Line 259-280: if response is None or status != 'ok' -> _log_warning, then continue
Line 287: self._callbacks[local_sub_id] = [callback] <- STILL REGISTERS CALLBACK
Line 294: return local_sub_id (success marker)

Callers see success (non-None sub_id returned), but callback never fires because server subscription failed. Silent degradation.
  - desc: GuiStateProxy.subscribe() returns success even if server subscription fails (network error, invalid pattern, server rejected). Callback is registered locally, but state.changed messages don't arrive because server never created the subscription. Caller sees no error, callback remains dormant. Degradation is silent.
  - dir: fix
- **[medium/framework] ProcessModule._init_state_proxy called in finally block during exception** `(process_communication_boundary_ipc_audit)`
  - kind: missing
  - evidence: multiprocess_framework/modules/process_module/core/process_module.py:178-179 (finally: calls _init_state_proxy() after initialize exits or raises). Line 268 guard: 'if self.state_proxy is None or self.router_manager is None: return'. If initialize() raised before router_manager was assigned (_init_managers, line 141), _init_state_proxy runs in finally but router_manager is None, so handler registration is skipped silently.
  - desc: State proxy handler registration (_init_state_proxy line 262-280) is called in finally block (line 179), which runs even if initialize() throws. If exception occurs before router_manager initialization (line 141), then router_manager will be None when finally runs. The guard (line 268) prevents crash but silently skips registration. This means state proxy is never wired on init failure, leading to silent state-update drops. Better: move _init_state_proxy to end of successful initialize path, or document exception-safety guarantees.
  - dir: fix
- **[medium/framework] Worker addressing (P2.2) silent message loss on handler exception** `(process_communication_boundary_ipc_audit)`
  - kind: leaky-abstraction
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:552-571 (_route_to_worker: if handler registered and raises Exception, logs warning line 570, returns True message consumed). Line 564-566 returns False if no handler (fallback to process-dispatch). If handler exists and throws, message is marked consumed (return True) but NOT processed.
  - desc: Worker addressing routes messages with _address=['proc','worker'] to registered worker handlers. If handler raises Exception, it's logged (line 570) and message is consumed (return True). This causes silent message loss: control-plane commands to workers that fail in handler are never retried or logged as errors. Exception is swallowed. For critical commands (process.stop, worker.pause_all), this could hang operations. Better: propagate exception, queue message to error handler, or retry with backoff.
  - dir: fix
- **[medium/framework] Троеность логики targets->queue в 3 местах** `(pipeline-communication-boundaries)`
  - kind: redundancy
  - evidence: send_to_process + _deliver_by_targets + broadcast all call queue_registry.send_to_queue; qtype-selection logic duplicated
  - desc: After _select_queue_type canonization, logic still scattered. Three entry points to queue_registry complicate debugging. Synchronization risk when filtering rules change.
  - dir: merge
- **[medium/framework] Mismatch async/sync in send_message ProcessCommunication vs RouterManager** `(pipeline-communication-boundaries)`
  - kind: leaky-abstraction
  - evidence: ProcessCommunication.send_message calls synchronous RouterManager.send; hot data path (SourceProducer tight loop) blocks on router.send
  - desc: Data frames sent synchronously (blocking send in hot loop). Router may stall on queue full. send_async exists but not used or documented. Should switch to async for data-plane.
  - dir: fix
- **[low/framework] Heartbeat sent before ProcessMonitor ready** `(lifecycle-bridge)`
  - kind: tight-coupling
  - evidence: ProcessModule.run() calls heartbeat.start() at line 613 AFTER register_commands_with_router() (line 607). ProcessMonitor.start() registers 'heartbeat' handler in router at line 99. Heartbeat worker polls on 5s interval (line 91, process_heartbeat.py), so startup race window is ~5s if ProcessManager.initialize() is delayed.
  - desc: ProcessHeartbeat.start() launches background worker at ProcessModule.run() time. First heartbeat message fires after 5-second interval default. If ProcessManager.initialize() hasn't called monitor.start() yet, heartbeat messages will be dropped (no handler registered). Handler registration happens in ProcessMonitor._register_heartbeat_handler() during ProcessManager.initialize() before child processes start, so race is theoretical but window exists if initialization is serialized.
  - dir: discuss
- **[low/framework] Channel suffix filtering logic inlined in _poll_all_channels** `(process_communication_boundary_ipc_audit)`
  - kind: leaky-abstraction
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:591-600. Suffix extraction: ch_name[len(prefix):] if prefix, else ch_name.split('_')[-1] if '_' in ch_name, else ch_name. Complex string logic; if channel naming changes (e.g., 'process_system' to 'process.system'), this breaks silently. No utility function for suffix extraction exists.
  - desc: The channel-type filtering via suffix matching (lines 591-600) is inline imperative string slicing. Extracting 'system'/'data' from 'process_system' uses complex fallback logic (slice by prefix length, then split by '_', then fallback to name). This is fragile: changing channel naming convention (e.g., from underscore to dot) requires updates in two places (here and in ProcessCommunication.register_router_channels line 100). Extract to utility function for resilience.
  - dir: fix
- **[low/plugins] ModbusSinkPlugin directly imports Services.modbus.ModbusDevice, bypasses plugin protocol isolation** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: tight-coupling
  - evidence: Plugins/sinks/modbus_sink/plugin.py:29 (from Services.modbus import ModbusConfig, ModbusDevice, ...) and line 115-127 (_build_device creates ModbusDevice directly) vs ADR-DS-006 which states plugin forbidden only multiprocess_prototype.*
  - desc: ModbusSinkPlugin is a Plugins-layer sink that directly instantiates Services.modbus.ModbusDevice (line 127). This breaks abstraction: the plugin should not create service objects directly but should either (1) receive device as dependency injection, or (2) send commands through ModbusPlugin via RouterManager. Current pattern couples Plugins.modbus_sink to Services.modbus internals, making it impossible to swap Modbus implementations or mock for testing without modifying the plugin. The docstring at line 13-15 explicitly notes this is allowed but treats it as an exception.
  - dir: discuss

### === smell ===

- **[medium/framework] DeltaDispatcher.dispatch returns count but no delivery confirmation** `(statestore-transport)`
  - kind: leaky-abstraction
  - evidence: multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py:44-85 — dispatch() returns {subscriber: delta_count}. multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py:98-132 — _send_state_changed() is void, sends async, has no return status. multiprocess_framework/modules/state_store_module/manager/state_store_manager.py:177 — caller ignores dispatch result.
  - desc: Dispatcher returns statistics (count per subscriber) but not delivery confirmation. _send_state_changed sends async and may fail silently (if router=None or router.send_async raises). Caller cannot know if message was actually sent. Failures hidden from middleware and diagnostics.
  - dir: discuss
- **[medium/framework] Inconsistent queue type selection (system vs data) lacks explicit semantic model** `(ipc-channel-map)`
  - kind: inconsistency
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:243-253 _select_queue_type() rule: explicit msg['queue_type'] OR (type=='command' ? 'system' : 'data'); comment at line 248-251 says this is temporary parity, redesign deferred to Phase 3 (P3).
  - desc: Queue selection heuristic (type=='command' implies system queue, else data) conflates routing with worker specialization. When Event/State channels introduced, this implicit mapping breaks. ADR-style comment acknowledges debt.
  - dir: discuss
- **[medium/framework] channel='data'/'system' vestigial in MESSAGE_TYPE_DEFAULTS** `(Channel Communication Map)`
  - kind: naming-trap
  - evidence: router_manager.py:874-877 guards against ch_name='queue' (legacy default). process_communication.py:206-211 explicitly strips channel='data'/'system' to avoid 'channel not registered' warnings on frames.
  - desc: MESSAGE_TYPE_DEFAULTS contains default channel names ('data','system') which are queue_type names, not IMessageChannel names. Real channels: {process}_{data,system}, system_events, {process}_local. Trap: code setting channel='data' expecting queue-type routing silently demotes to U1 fallback.
  - dir: fix
- **[medium/framework] queue_registry.send_to_queue dominates egress (architectural bypass)** `(Channel Communication Map)`
  - kind: tight-coupling
  - evidence: ProcessCommunication.send_to_process (line 213) calls queue_registry.send_to_queue directly, bypassing router.send(). Frames, commands, state updates all use this path. RouterManager._deliver_by_targets (fallback, 255-315) also calls queue_registry.
  - desc: 90% of IPC traffic bypasses RouterManager routing logic (AsyncSender, middleware, channel_dispatcher). Router becomes thin wrapper around queue_registry. This is by design (ADR-RTR-006 likely) but documents as 'optional infrastructure'.
  - dir: discuss
- **[medium/services] ProcessCommunication.send_message bypasses router send middleware** `(Channel Communication Map)`
  - kind: leaky-abstraction
  - evidence: process_communication.py:200-218 (send_message) calls queue_registry.send_to_queue directly. Does NOT call router.send(msg). Result: send_middleware (logger, audit, throttle) never applied to 90% of data-plane traffic.
  - desc: Services use send_message directly, bypassing middleware chain defined in RouterManager. Not a correctness bug (middleware is informational) but consistency issue for audit/logging.
  - dir: fix
- **[medium/services] CommandSender invoked only for register_update; no address resolution for other commands** `(buses-action)`
  - kind: leaky-abstraction
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\app.py:529-533 (register_update via CommandSender with resolve_plugin_register)
vs bridge.plugin_register_resolver.resolve_plugin_register (app.py:509) invoked ONLY in _on_plugin_config_changed listener at line 500-544. No similar resolution logic for other command types.
  - desc: PluginConfigChanged events are routed through command_sender.send_command with explicit address resolution (process_name, register name via resolve_plugin_register). However, CommandSender is a thin wrapper that delegates to build_command_message without knowing about plugin index vs. register name mapping. For other mutation types (topology changes, process start/stop), CommandSender is used without the same address resolution. This creates an inconsistency and leaks abstraction: address resolution logic lives in event listeners rather than in CommandSender.
  - dir: discuss
- **[medium/framework] EventBus handler registration order critical but fragile** `(buses-action)`
  - kind: naming-trap
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\app.py:492-496 (warning about ordering)
vs app.py:477 (TopologyReplaced subscribe) and line 545 (PluginConfigChanged subscribe)

Comment states: 'TopologyReplaced приходит ПЕРЕД PluginConfigChanged... Не переставлять без анализа.'
  - desc: EventBus handler registration order is critical: TopologyReplaced must be published before PluginConfigChanged so that PipelinePresenter and TopologyBridge finish cache invalidation before register_update listener fires (line 500-544). The order is fragile: it depends on subscription order in app.py. If a new handler is added for TopologyReplaced between these lines, it breaks the ordering assumption. EventBus doesn't enforce or document ordering guarantees.
  - dir: fix
- **[medium/framework] Vestigial msg['channel']='data' blocks routing resolution (recon #3)** `(prototype-communication-map)`
  - kind: vestigial
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\router_module\routing\address_aware_channel.py:24-27
d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\router_module\tests\test_router_manager.py:967-975

Test comment documents: recon #3 - frame messages carry vestigial channel='data' (literal string, not resolved to {process}_data). When resolver tries channel_dispatcher.dispatch(), it encounters channel='data' which doesn't exist in registry. Per ADR decision, this field should be stripped before routing.
  - desc: Frame messages and possibly other payloads carry msg['channel']='data' (a literal string, not resolved to {process}_data). When router tries to resolve channels via channel_dispatcher or _resolve_channels(), it encounters this literal 'data' which doesn't exist in the channel registry. Per ADR-RTR-003 (recon #3 decision), this field should be stripped from data-billets before routing -- it's legacy from an earlier design.
  - dir: fix
- **[medium/mixed] FormContext.write binding-aware path exists but form_ctx=None makes it unreachable** `(prototype-communication-map)`
  - kind: tight-coupling
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\forms\factory.py:231 (CheckboxControl: 'cherez FormContext.write'), line 528 (NumericControl: 'Legacy put form_ctx=None sozdaet raw QSpinBox bez ActionBus-binding')

All form controls (CheckboxControl, SpinBoxControl, SliderControl, ComboControl) have binding-aware path IF form_ctx passed. But factory.build_form() called with form_ctx=None in many contexts. Result: binding (ActionBus coalescing, undo, remote sync) silently skipped.
  - desc: Form factory functions have two paths: form_ctx-aware (binding, ActionBus, undo) and form_ctx=None (raw widget, no coalescing). When form_ctx=None (default), binding-aware path is unreachable -- widgets don't report changes, no undo/redo, no ActionBus integration. Callers don't always know form_ctx is required.
  - dir: discuss
- **[medium/mixed] Parallel undo/redo systems: framework ActionBus vs domain CommandDispatcher** `(prototype-communication-map)`
  - kind: redundancy
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\windows\main_window.py:282 (comment: 'konflikt dvuh parallelnyh undo')

ActionBus: max_history=200 stacks, coalescing, handlers (FieldSetHandler, TopologyHandler, RecipeHandler). Domain CommandDispatcher: snapshot-based undo. Global undo (Ctrl+Z) routed to domain via window.set_undo_controller(). ActionBus handlers registered but unreachable from production.
  - desc: Two independent undo/redo engines coexist: legacy ActionBus (framework/actions_module) with handlers and coalescing vs domain CommandDispatcher (adapter, snapshot-based). Global undo routed to domain. ActionBus handlers registered but unreachable from production. Zoning decision not fully enforced: framework still exports undo infra (Action, ActionBuilder, ActionBus), but app uses domain exclusively.
  - dir: discuss
- **[medium/framework] Framework carries unused subsystems unmotivated by prototype (ActionBus, FrontendManager, chain_module, WorkerPoolDispatcher)** `(prototype-communication-map)`
  - kind: misplaced-layer
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\docs\COMMUNICATION_MAP.md:227

Framework exports ActionBus, ActionHandler, ActionBuilder -- 0 uses in prototype.
Framework has chain_module/, frontend_module/ with FrontendManager, RouterSchemaAdapter -- never instantiated.
Framework actions_module/handlers/: FieldSetHandler, TopologyHandler, RecipeHandler -- registered but unreachable.

No ADR blocking exports. No deletion because 'konstruktor-zadel' (constructor foundation). But they litter API and create false narrative of system design.
  - desc: Framework module exports and submodules (actions_module, frontend_module, chain_module) carry capabilities never consumed by Inspector prototype. They exist as foundation for future domain migrations ('konstruktor-zadel'), but inflate the public API and create misleading examples. The prototype is first consumer but doesn't need these -- creates false impression of framework maturity.
  - dir: discuss
- **[medium/services] StateProxy.subscribe() response uses 'status' field but code checks for field mismatch** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: inconsistency
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:267
    elif response.get("status") != "ok": <- Client checks response.status

multiprocess_framework/modules/state_store_module/manager/state_store_manager.py:272
    return {"status": "ok", "sub_id": sub_id}  <- Server returns status field

multiprocess_framework/modules/router_module/core/router_manager.py:443
    "success": success, <- RouterManager.reply_to_request() uses 'success' in response envelope
  - desc: StateProxy checks response.get('status') == 'ok' (line 267, 176, 209), but RouterManager.request() and reply_to_request() use 'success' field in top-level response envelope (line 443, 901). StateStoreManager returns {"status": "ok", ...} which is correct for its domain, but if the response goes through RouterManager.reply_to_request() wrapper, the top-level envelope will have 'success' not 'status'. StateProxy client code assumes 'status' exists but does not guard for missing field.
  - dir: discuss
- **[medium/framework] BackendDriver request_id vs RouterManager correlation_id vs StateProxy: naming trap, subscribe ignores pattern** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: naming-trap
  - evidence: backend_ctl/driver.py:118-119
    cid = message.get('request_id') or str(uuid.uuid4())
    message['request_id'] = cid

multiprocess_framework/modules/router_module/core/router_manager.py:362-368
    msg['request_id'] = cid
    data.setdefault('correlation_id', cid)  <- Mirroring for compat

multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:243-253
    NO request_id in subscribe message <- StateProxy ignores the pattern
  - desc: Three different naming schemes for correlation: (1) BackendDriver uses top-level request_id, (2) RouterManager.request() mirrors to data.correlation_id for backward compat with ProcessManager.process.command, (3) StateProxy does NOT follow either pattern -- it sends command with NO correlation_id at all. _extract_correlation_id() (line 322-336) checks request_id first, then data.correlation_id, which works for driver and ProcessManager but StateProxy falls out. Naming trap: 'request_id' is TCP/BackendDriver term, 'correlation_id' is nested PM term, but subscribe never gets either.
  - dir: fix
- **[medium/framework] RouterManager.receive() type='response' self-resolve guard lacks idempotence check, echoed requests captured** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: tight-coupling
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:496-507
    if self._pending_requests and processed.get('type') == 'response':
        cid = self._extract_correlation_id(processed)
        if cid and self._resolve_pending(cid, processed):
            self._inc_stat('received')
            continue
  - desc: Guard checks type='response' (line 503) but does NOT check if the response ID matches request we SENT vs request sent BY us. Edge case: BackendDriver sends request_id=X, waits for response. Meanwhile, external process sends command with request_id=X expecting US to respond. Both messages have type='response' + request_id=X. Second message will be captured as response to first request (false match) and never dispatched to handlers. Risk is low (requires id collision + timing), but guard is incomplete. Should also check sender != self.process.name or maintain separate namespace for incoming vs outgoing correlation IDs.
  - dir: discuss
- **[medium/framework] SystemThreads._message_processing_loop redundant with router.receive() message_dispatcher** `(process_communication_boundary_ipc_audit)`
  - kind: missing
  - evidence: multiprocess_framework/modules/process_module/threads/system_threads.py:70-75 (loop calls router.receive(channel_types=['system']), then _handle_message for each message). multiprocess_framework/modules/router_module/core/router_manager.py:517-526 (receive() calls message_dispatcher.dispatch at line 520-523 BEFORE returning). multiprocess_framework/modules/process_module/threads/system_threads.py:88-94 (_handle_message checks type=='command' and returns; comment: 'komandy obrabatyvayutsya v receive()'). Command dispatch happens in receive() (line 520), not in _handle_message (line 93-94 returns early).
  - desc: Message processor thread appears to process commands, but router.receive() has already dispatched them via message_dispatcher (line 520-523). _handle_message then checks type=='command' and no-ops (line 93-94). This design (documented in comment line 88-89) prevents race between system_thread and workers, but code organization is confusing: message_processor_loop receives messages AFTER dispatch, so it cannot intercept or re-route them. Thread runs but does no actual message work. Design is sound (isolate system thread from worker race), but naming misleads.
  - dir: discuss
- **[medium/framework] Vestigial channel field ('data'/'system') hard to eradicate** `(pipeline-communication-boundaries)`
  - kind: naming-trap
  - evidence: source_producer/pipeline_executor write channel='data'; send_to_process deletes it. Not registered as real channel. Implicit qtype filter.
  - desc: Design conflict: old model (channel = literal queue name) vs new (channel = prefix in {proc}_data). Migration incomplete. Code writes field that gets silently removed. Reads as magic.
  - dir: discuss
- **[medium/framework] Asymmetry state_proxy init: register 'state.changed' only** `(pipeline-communication-boundaries)`
  - kind: leaky-abstraction
  - evidence: process_module.py:271 registers on_state_changed handler; 'state.subscribe' not registered. StateStoreManager.register_message_handlers exists but orchestrator skips it
  - desc: Protocol asymmetry: inbound (on_state_changed) explicitly registered in router; outbound (subscribe/set/merge) sent directly without handler registration on receiver. Init incomplete.
  - dir: fix
- **[medium/framework] vestigial channel='data'/'system' stripped post-hoc** `(comm-systems-census)`
  - kind: naming-trap
  - evidence: process_communication.py:206-211 strips channel if 'data' or 'system' with vestigial comment. Producers still set these fields.
  - desc: Old spec had channel field (routing hint), new spec uses targets+queue_type. Producers still set channel, send_to_process() strips post-hoc. Naming confusion.
  - dir: fix
- **[medium/services] SQL service bypasses RouterManager entirely: execute_command() called directly, no channel registration** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: tight-coupling
  - evidence: Services/sql/core/sql_manager.py:275-299 (execute_command dict dispatch: db.query/db.execute/db.insert) vs Services/modbus/channels/modbus_channel.py (ModbusChannel implements IMessageChannel with send/poll); no SQL service channel found in codebase
  - desc: Modbus service follows the P4 framework pattern: ModbusChannel registers as a named channel in RouterManager, commands flow through send() with unified envelope {command/op/data/channel}, responses return dict with status. SQL service does NOT follow this pattern: SQLManager.execute_command() is called directly by consumers (process adapter, topology manager) without RouterManager mediation. Commands are plain dict with {command: 'db.query'/'db.execute'/'db.insert', args/data, sql, params} but this envelope diverges from framework standard and is not routed through channels. This creates inconsistency: same architecture (dict-at-boundary IPC) but two different wiring patterns.
  - dir: discuss
- **[low/framework] StateProxy.get synchronous fallback has no timeout or backoff** `(statestore-transport)`
  - kind: missing
  - evidence: multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:145-183 — StateProxy.get() calls _send_sync(msg), which calls router.send(msg) (synchronous blocking call). No timeout parameter in get() itself; relies on RouterManager.send internal timeout. Caller thread can hang indefinitely if StateStoreManager slow.
  - desc: StateProxy.get is cache fallback (after cache miss) that blocks caller thread. If router/server slow, caller hangs. No timeout or retry mechanism at StateProxy level. Comment says 'IPC fallback' but provides no safeguard.
  - dir: discuss
- **[low/framework] Hierarchical addressing (P0.2) — asymmetric implementation** `(envelope-field-mapping)`
  - kind: missing
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:294-315 (send) vs 536-571 (receive)

Send: split_address() → _address in ticket
Receive: _route_to_worker() only if handlers dict non-empty
  - desc: Addressing contract partially implemented: send side splits dotted targets into _address, but receive side routes ONLY if _worker_handlers registered (fast-exit). No invariant prevents silent fallthrough.
  - dir: discuss
- **[low/framework] correlation_id vs request_id — dual naming for P0.5** `(envelope-field-mapping)`
  - kind: naming-trap
  - evidence: multiprocess_framework/modules/router_manager.py:322-336: _extract_correlation_id() returns request_id
No unified terminology in codebase.
  - desc: Router uses 'request_id' (top-level) and 'data.correlation_id' (PM wrapper). Function named _extract_correlation_id returns request_id. Terminology mismatch confuses scope.
  - dir: discuss
- **[low/prototype] Frame broadcast naming inconsistency (frame.camera_ID vs display.ID)** `(ipc-channel-map)`
  - kind: naming-trap
  - evidence: multiprocess_prototype/backend/routing/frame_router_setup.py:26-28 defines 'frame.camera_{id}'; multiprocess_prototype/frontend/widgets/displays/preview_window.py:84 uses 'display.{id}'. Different schemes for camera vs display broadcasts.
  - desc: Two broadcast patterns coexist (cameras vs displays) with inconsistent naming. Not a bug, design choice, but confusing documentation gap.
  - dir: discuss
- **[low/framework] CommandDispatcher duplicates message_dispatcher traversal** `(lifecycle-bridge)`
  - kind: redundancy
  - evidence: ProcessLifecycle.register_commands_with_router() (lines 115-127) iterates command_manager.get_commands() and calls register_message_handler for each. ProcessModule.run() (line 607) repeats this iteration with identical logic.
  - desc: The re-sync at line 607 ensures builtin commands (registered at line 599) are visible to router.message_dispatcher. Implementation is correct (idempotent), but the double iteration of command registry on every startup creates O(n) overhead proportional to command count. For typical processes (5-15 commands), cost is <1ms but violates DRY principle.
  - dir: fix
- **[low/framework] Vestigial channel names 'data'/'system' stripped defensively but unmapped** `(buses-action)`
  - kind: naming-trap
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\process_module\communication\process_communication.py:210

if message.get("channel") in ("data", "system"):
    message.pop("channel", None)

Comment at line 206: 'vestigial channel="data"/"system"'
  - desc: process_communication.py strips legacy channel names 'data' and 'system' from messages before routing through RouterManager, treating them as non-existent qtypes (real channels are 'system_events', '{proc}_data', '{proc}_local'). The defensive stripping prevents errors but the names are confusing for maintainers: they suggest channels that don't exist in the registry. This is a naming trap for future developers.
  - dir: discuss
- **[low/framework] state.changed routed to {subscriber}_system queue but queue_type metadata unclear** `(prototype-communication-map)`
  - kind: inconsistency
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\state_store_module\manager\delta_dispatcher.py:98-127

Line 115: msg['queue_type'] = 'system'
Line 110: msg['targets'] = [subscriber]
Line 124: self._router.send_async(message)

Comment (lines 113-114): 'dostavka v {subscriber}_system, kotoryj opraschivaet shtajnyj message_processor' (delivery to {subscriber}_system via message_processor). But U1-fallback is invoked when channel resolution FAILS -- two different broadcast paths.
  - desc: state.changed message set queue_type='system' and delivered via targets=[subscriber] to ProcessManager's queue_registry, which uses U1-fallback (_deliver_by_targets). This is a workaround for channel resolution not routing state-messages. queue_type metadata is hint-like, not binding -- routing decision made at send time via targets, not queue_type.
  - dir: discuss
- **[low/framework] ProcessHeartbeat sends to ProcessManager but no acknowledge or timeout recovery** `(prototype-communication-map)`
  - kind: missing
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\process_module\heartbeat\process_heartbeat.py:65-91

Line 86: self._services.send_message('ProcessManager', heartbeat_msg) -- one-way send, fire-and-forget.
No receive() for heartbeat_ack, no timeout recovery, no backoff if ProcessManager unresponsive.
Heartbeat loop catches exceptions but treats all failures same (sleep on error, continue).
  - desc: Heartbeat sender (ProcessHeartbeat._loop) sends type='system' subtype='heartbeat' every 5s to ProcessManager, but has no acknowledgement mechanism or response handling. If ProcessManager queue fills or router fails, heartbeat will silently drop. No per-process heartbeat timeout = no dead-process detection on receiver side.
  - dir: discuss
- **[low/framework] Delta.to_dict() serialization format assumed by GuiStateProxy but not enforced by contract** `(prototype-communication-map)`
  - kind: leaky-abstraction
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\state_store_module\manager\delta_dispatcher.py:118

Line 118: 'deltas': [d.to_dict() for d in deltas]

d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_framework\modules\state_store_module\proxy\state_proxy.py:336-341

DeltaDispatcher serializes with to_dict(). StateProxy deserializes assuming Delta-compatible dict (path, old_value, new_value). No Protocol or formal contract specifies format.
  - desc: DeltaDispatcher sends state.changed by serializing Delta objects with to_dict(). StateProxy deserializes assuming Delta-compatible dict structure (path, old_value, new_value). No Protocol or formal contract specifies Delta.to_dict() schema -- coupling is implicit.
  - dir: discuss
- **[low/framework] RouterManager._select_queue_type() auto-selects 'system' for type='command', hardcodes control-plane routing** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: tight-coupling
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:242-253
    @staticmethod
    def _select_queue_type(msg_dict: Dict[str, Any]) -> str:
        return msg_dict.get('queue_type') or ('system' if msg_dict.get('type') == 'command' else 'data')

Comment line 246-251 explains: static rule will change when P3 adds Event/State channels
  - desc: Queue type is statically mapped: all commands -> system queue, all data -> data queue. This is rule-of-thumb for P0.5 but becomes problematic when (1) new message types (Event, State) are added (P3), or (2) request-response over data-plane is needed. The static assignment is baked into channel-register-time (queue_config keys), not payload-driven. StateStoreManager.handle_state_subscribe sends response with type='response' which gets system queue (good for control-plane), but if state.changed (push) is type='data', it gets data queue -- divergent handling for semantically related messages.
  - dir: discuss
- **[low/framework] RouterManager.reply_to_request() hardcodes response_command='command.response', breaks custom protocol semantics** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: misplaced-layer
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:410-446
    def reply_to_request(
        self,
        request_msg: Dict[str, Any],
        result: Any,
        success: bool = True,
        response_command: str = "command.response",  <- Default hardcoded
    ) -> Optional[Dict[str, Any]]:
  - desc: reply_to_request() has response_command parameter (line 415) defaulting to 'command.response' -- suggesting it can be customized. But caller ProcessLifecycle and ProcessManagerProcess._handle_process_command hardcode the argument. This is framework code imposing PM-specific naming ('process.command.response') on generic P0.5 layer. If request had command='state.subscribe', response should logically be 'state.subscribe.response' not 'command.response'. Parameter is unused flexibility; better to derive response_command from request.command on framework side.
  - dir: discuss
- **[low/framework] RouterManager.request() pending awaits in different thread than receive(), contract not guarded** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: tight-coupling
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:338-394
    def request(self, message, timeout=5.0, correlation_id=None):
        pending = _PendingRequest()  <- Created in caller thread
        with self._pending_lock:
            self._pending_requests[cid] = pending
        try:
            if not pending.event.wait(timeout):  <- Blocks caller
  - desc: Thread model: request() blocks caller thread (GUI or backend_ctl), registers pending slot, calls send() (blocking), then waits for event. receive() runs in different thread (system_thread or worker thread), polls channels, finds response, calls _resolve_pending() to set event. Lock guards _pending_requests dict (line 121) but contract depends on caller NOT being the thread that runs receive(). If caller invokes request() from the same thread as receive() loop, event.wait() will deadlock (mentioned in docstring line 350-353). This is not a bug if contract is followed, but it's a latent fault: no guard prevents mis-usage. Should document as CRITICAL or add thread affinity check.
  - dir: discuss
- **[low/framework] Request-response (P0.5) self-resolve guard allows response-type echo injection** `(process_communication_boundary_ipc_audit)`
  - kind: tight-coupling
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:503-507 (receive checks 'if self._pending_requests and processed.get("type") == "response"' before _resolve_pending). Lines 496-502 explain: guard ensures command echoes (self-targeted commands) aren't consumed by pending resolver. Type=='response' check ensures only responses are resolved.
  - desc: Guard on line 503 (type=='response') ensures command echoes don't get consumed as responses. But any response-type message with matching correlation_id will be resolved by pending request, even if no corresponding request() was made (old/spoofed correlation_id). Weak against reflection attacks. In high-concurrency scenarios, a response intended for old request could match new pending request with same ID (though uuid4 makes this unlikely). Better: return correlation_id to requester before sending, validate correlation_id matches sent request exactly.
  - dir: discuss
- **[low/framework] Heartbeat message carries redundant envelope fields** `(comm-systems-census)`
  - kind: redundancy
  - evidence: process_heartbeat.py:65-86 heartbeat_msg type/subtype/command all 'heartbeat'; process_monitor.py:200-220 extracts only workers_status, ignores envelope.
  - desc: Heartbeat message has redundant type/subtype/command fields never examined. Workers status only payload extracted.
  - dir: fix
- **[low/services] Envelope field ambiguity: 'command' vs 'op' in ModbusChannel (accept both, document neither clearly)** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: naming-trap
  - evidence: Services/modbus/channels/modbus_channel.py:112 (command = str(message.get('command') or message.get('op') or ''))
  - desc: ModbusChannel.send() accepts either 'command' or 'op' field in the message dict and treats them equivalently. This is a convenience for backward compatibility but creates ambiguity: callers don't know which field is canonical. The build_command_message() builder always uses 'command', but send() treats 'op' as a fallback. This is fragile: if both fields exist with different values, behavior is undefined (whichever appears first in message.get() wins).
  - dir: discuss

### === unused-capability ===

- **[high/framework] channel_dispatcher underused for egress routing (80-90% traffic bypasses)** `(Channel Communication Map)`
  - kind: leaky-abstraction
  - evidence: router_manager.py:654-691 (register_route/register_broadcast_route) initialize dispatcher, but _deliver_by_targets (255-315) dominates: queue_registry.send_to_queue(process_name) fallback used for ~90% traffic. Only frame fan-out (frame_router_setup.py) + EventManager.emit_event (optional) use channel_dispatcher.
  - desc: channel_dispatcher is expensive infrastructure (EXACT_MATCH, PATTERN_MATCH, broadcast) but only EventManager.emit_event routes via system_events. All command/frame/state traffic uses U1 fallback (targets+qtype). Message flow is fire-and-forget queue delivery + type-dispatch (message_dispatcher), not channel-routed.
  - dir: discuss
- **[medium/framework] Channel names 'data'/'system' stripped pre-send** `(lifecycle-bridge)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/process_module/communication/process_communication.py:206-211; if message.get('channel') in ('data', 'system'): message.pop('channel', None). Comment (lines 206-207): 'vestigial channel — это ИМЯ qtype, а не зарегистрированный канал'.
  - desc: ProcessCommunication.send_to_process() explicitly removes 'channel' field if it's 'data' or 'system' (lines 210-211) to avoid "channel not registered" warnings on every frame. These names are legacy queue-type hints, not actual router channels. Real channels are named targets_{qtype}, system_events, {proc}_local. Stripping prevents IPC-log spam but indicates semantic confusion between queue-types and channel names.
  - dir: fix
- **[medium/prototype] GuiStateProxy handler not auto-registered via ADR-SS-006** `(lifecycle-bridge)`
  - kind: missing
  - evidence: multiprocess_prototype/frontend/process.py:88-91; GuiProcess._init_application_threads() manually calls router_manager.register_message_handler('state.changed', ...) instead of relying on ProcessModule._init_state_proxy() (which requires state_proxy param). Comment (line 88-90) justifies: 'don't activate third-party GUI adapters, avoid double registration'.
  - desc: ProcessModule.initialize() offers automatic state proxy registration via _init_state_proxy() (line 271, if state_proxy is passed to __init__). GuiProcess explicitly avoids this by setting self.state_proxy=None and manually registering in _init_application_threads(). This breaks the ADR-SS-006 contract and requires hand-wiring in every GUI process. Risk: future processes may forget registration, causing silent state.changed drops.
  - dir: discuss
- **[medium/prototype] FormContext.write() calls action_bus.execute() when form_ctx=None: ActionBus dead in inspector** `(request-reply boundary: RouterManager.request / _resolve_pending / reply_to_request)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/frontend_module/forms/form_context.py:90
    result = self.action_bus.execute(action) <- execute() always called

multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py:162-167
    form_ctx = None  <- Explicitly set to None (TODO Phase G.4)
    for field_info in fields:
        editor = CardsFieldFactory.create(
            field_info,
            parent=self._params_widget,
            form_ctx=form_ctx,  <- None passed, so FormContext never instantiated
  - desc: NodeInspectorPanel hardcodes form_ctx=None (line 162, comment 'TODO Phase G') before calling CardsFieldFactory. FormContext requires action_bus (line 51), but with form_ctx=None, CardsFieldFactory never creates FormContext instances. FormContext.write() method (line 57-100) is unreachable from inspector. ActionBus.execute() (line 90) is never invoked from this panel. This is a framework capability that prototype intentionally bypasses because AppServices does not yet provide form_context(). Result: inspector falls back to legacy direct RegisterAdapter writes (line 167 comment), losing undo/redo and field coalescing.
  - dir: discuss
- **[medium/services] HikvisionCameraPlugin produces frames but does not register RouterManager channel for telemetry/commands** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: missing
  - evidence: Services/hikvision_camera/plugin/plugin.py:145-187 (produce() returns dict with frame + metadata, NO channel registration code observed) vs Services/modbus/plugin/plugin.py:103-135 (_register_channel creates ModbusChannel and registers in RouterManager)
  - desc: HikvisionCameraPlugin is a source (produce) that returns frame dicts. Unlike ModbusPlugin, it does not: (1) create a HikvisionChannel(IMessageChannel); (2) register channel in RouterManager for command routing (open/close/start_capture/stop_capture are defined as cmd_*() methods in plugin.commands dict but NOT wired through channel); (3) export telemetry through channel.poll(). Commands exist (enum_devices, get_parameters, set_parameters, set_exposure, set_gain, set_frame_rate, set_resolution, open_sdk_app, close_sdk_app) but they execute only through plugin command dispatch, not through RouterManager. This is inconsistent with Modbus and means Hikvision cannot be controlled via router.send() like other services.
  - dir: discuss
- **[low/framework] expects_full_message parameter unused in message handler registration** `(statestore-transport)`
  - kind: redundancy
  - evidence: multiprocess_framework/modules/state_store_module/manager/state_store_manager.py:392 — register_message_handlers passes expects_full_message=True. multiprocess_framework/modules/router_module/core/router_manager.py:714-732 — register_message_handler accepts but only forwards to dispatcher; has no effect on StateStoreManager's behavior. All handlers always receive full message dict.
  - desc: expects_full_message is vestigial. StateStoreManager always passes True, always receives full messages, always normalizes via _extract_data(). The flag exists but has no observable effect on message routing or filtering for state store operations.
  - dir: discuss
- **[low/framework] Vestigial 'data' queue_type fallback never used by StateStore** `(statestore-transport)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:243-253 — _select_queue_type fallback rule sends non-command messages to 'data' queue. multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py:115 — DeltaDispatcher explicitly sets queue_type='system' for all state.changed messages. No StateStore message ever triggers 'data' fallback.
  - desc: RouterManager._select_queue_type has logic to route messages to 'data' queue as fallback for non-command types. But state.changed always explicitly sets queue_type='system' (delta_dispatcher.py line 115). Comment suggests 'Event/State-channels (P3)' for future phases never implemented. State transport has zero dependency on 'data' queue path.
  - dir: discuss
- **[low/framework] Message.subtype — set by ProcessMonitor, never routed** `(envelope-field-mapping)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:534, 580: sets 'subtype'
BUT: Message schema has no subtype field; message_dispatcher ignores it.
  - desc: ProcessMonitor sets msg['subtype'] but Message.schema lacks field, routers ignore it. Abandoned P0.x design artifact.
  - dir: discuss
- **[low/framework] Message.data — overloaded catch-all container** `(envelope-field-mapping)`
  - kind: leaky-abstraction
  - evidence: multiprocess_framework/modules/message_module/core/message.py:93

Used as: command args, state deltas, system event payload, set request data
No schema boundary; duck-typing required.
  - desc: Message.data is catch-all for unstructured payload. No schema enforcement across types. Handlers must duck-type and validate at dispatch time.
  - dir: discuss
- **[low/prototype] Vestigial 'channel' field in frame messages** `(ipc-channel-map)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/router_module/core/router_manager.py:265-267 comment: 'vestigial channel:data u kadrov already proven NOT resolved'. Frame messages may set channel='data' but _resolve_channels returns None, falling back to targets.
  - desc: Some frame implementations may set 'channel' field (legacy pattern) but modern routing uses targets-based broadcast fan-out. Channel field ignored if no broadcast route matches. Redundant and confusing.
  - dir: fix
- **[low/framework] frame_router_setup _get_route_channels assumes Dispatcher internal structure** `(Channel Communication Map)`
  - kind: missing
  - evidence: backend/routing/frame_router_setup.py:84-97 calls dispatcher.get_handler(route_key) and assumes it returns handler list directly. No validation that subscribe_to_camera actually updates route. No runtime test.
  - desc: Pattern is correct (register_broadcast_route + re-register to update), but _get_route_channels is fragile. If Dispatcher.get_handler signature changes, breaks. Recommendation: add RouterManager.get_route_info() public API or document Dispatcher.get_handler as internal.
  - dir: discuss
- **[low/framework] EventManager.emit_event optional router path (system_events unused)** `(Channel Communication Map)`
  - kind: missing
  - evidence: shared_resources_module/events/core/manager.py:127-140 (emit_event router branch) guarded by if self._router_manager. When None, skips cross-process dispatch. No ProcessManager code consumes system_events messages.
  - desc: EventManager.emit_event can send to system_events channel (cross-process) but router_manager optional. No consumer handler registered. Result: framework-provided capability unused by prototype.
  - dir: discuss
- **[low/services] FormContext.write binding-aware path unused in SettingsTab; form_ctx=None for system forms** `(buses-action)`
  - kind: missing
  - evidence: d:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\multiprocess_prototype\frontend\widgets\tabs\settings\system\section.py:84-95

# form_ctx=None: SettingsSystem не использует plugin binding.
return RegisterView(fields, form_ctx=None, ...)

Contrast: InspectorPanel passes form_ctx (pipeline/inspector/inspector_panel.py line 828)
  - desc: CardsFieldFactory supports two paths: binding-aware (form_ctx passed, uses FormContext.write + ActionBus coalescing) and legacy (form_ctx=None, raw Qt widgets). SettingsTab and PluginsTab intentionally pass form_ctx=None, meaning field edits don't go through ActionBus or binding-aware write. This is documented as intentional but means a significant portion of the form-building infrastructure is unused in those tabs.
  - dir: discuss
- **[low/framework] Message.channel field vestigial; queue_type derives from message.type only** `(process_communication_boundary_ipc_audit)`
  - kind: missing
  - evidence: multiprocess_framework/modules/message_module/core/message.py:71 (channel field defined). multiprocess_framework/modules/router_module/core/router_manager.py:243-253 (_select_queue_type: returns msg['queue_type'] or ('system' if type=='command' else 'data'). Never uses channel field). multiprocess_framework/modules/process_module/communication/process_communication.py:210-211 (strips vestigial channel='data'/'system', comment: 'recon #3, stripped').
  - desc: Message.channel is a schema field but unused in routing. Queue selection (_select_queue_type line 243-253) derives from message.type only, ignoring channel. ProcessCommunication.send_to_process explicitly removes channel='data'/'system' (line 210-211) to prevent spurious 'channel not found' warnings. This is documented as legacy (COMMUNICATION_MAP.md:238) but confuses callers: setting msg.channel has no effect on delivery. Callable but not live; framework capability unexercised.
  - dir: discuss
- **[low/framework] Vestigial 'data'/'system' channel name fields in message envelope (recon #3)** `(Services Communication Architecture: Channels/Commands/Subscriptions Map - IPC Audit)`
  - kind: vestigial
  - evidence: multiprocess_framework/modules/router_module/tests/test_router_manager.py:966-985 (test_vestigial_unregistered_channel_still_delivered_by_targets: msg['channel']='data' is intentionally unregistered, delivery falls back to targets[0]); multiprocess_framework/modules/router_module/routing/address_aware_channel.py:24-27 (recon #3 notes: vestigial channel:'data' blocks resolve, solution: remove from envelope)
  - desc: Historical message format included explicit 'channel' field (e.g., {'channel': 'data', ...}) to indicate message kind. This was a source of confusion because actual routing uses 'type' field + resolve_channel_kind() logic to map to channel-kind (system/data/event/state/log). The 'channel' field in messages is now vestigial: (1) when a registered ModbusChannel exists, msg['channel'] is ignored in favor of named route; (2) when no channel is registered, fallback logic uses msg['targets'] to find the queue, still ignoring the string 'channel' field. Test explicitly documents this: 'channel="data"' unregistered is still delivered by fallback to targets.
  - dir: discuss
