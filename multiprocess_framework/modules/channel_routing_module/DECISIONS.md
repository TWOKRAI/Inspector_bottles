# channel_routing_module — Архитектурные решения

> Ссылки на глобальные решения: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-CRM-001 (was ADR-013): Паттерн CRM (ChannelRoutingManager)

**Статус:** принято (2026-03-12)

**Контекст:** LoggerManager, ErrorManager, RouterManager дублировали логику маршрутизации.

**Решение:** Единый базовый класс `ChannelRoutingManager` = `BaseManager` + `ObservableMixin` + `ChannelRegistry` + `Dispatcher` + опционально `IBufferStrategy`.

**Следствие:** Все канальные менеджеры наследуют CRM, добавляя только доменную логику.

## ADR-CRM-002 (was ADR-014): Три стратегии буферизации

**Статус:** принято

- `DirectBuffer` — без буферизации (тесты, простые случаи).
- `BatchBuffer` — deque + timer (`LoggerManager`: batch flush по size/interval).
- `AsyncSenderBuffer` — PriorityQueue + фоновый поток (`RouterManager`: async send).

## ADR-CRM-003 (was ADR-015): RouterManager не использует IBufferStrategy из CRM

**Статус:** принято

**Контекст:** RouterManager имеет собственный async sender buffer, интегрированный с channel dispatcher.

**Решение:** RouterManager передаёт `buffer_strategy=None` в CRM и управляет буфером самостоятельно (см. также глобальный ADR-015 в [`../../DECISIONS.md`](../../DECISIONS.md)).

## ADR-CRM-004 (was ADR-016): register_broadcast() для мультиканальной доставки

**Статус:** принято

**Решение:** `register_broadcast(key, [ch1, ch2])` регистрирует обёртку, которая вызывает `write()` на всех указанных каналах.

## ADR-CRM-005 (was ADR-108): Две роли конфигов (ChannelRoutingConfig vs ChannelRoutingManagerConfig)

**Статус:** принято (2026-03-31)

- `core/config.py` — `ChannelRoutingConfig(SchemaBase)` — базовый runtime-конфиг; от него наследуют `LoggerManagerConfig`, `RouterManagerConfig` и др.
- `configs/channel_routing_manager_config.py` — `ChannelRoutingManagerConfig(SchemaBase)` — плоская схема для реестра схем / UI.

**Причина:** унифицированный `build()` у наследников `ChannelRoutingConfig` давал разные структуры; отдельная flat-схема решает задачу регистрации без цепочки `core`.

## ADR-CRM-006: Observability Control Plane — точки расширения (design-for-extension)

**Статус:** принято (2026-06-05)

**Контекст:** план `observability-control-plane` построил контур: `reconfigure(config: dict)` на
CRM (Phase 1, через хук `_rebuild_from_config`), реестр sink-фабрик `register_sink_factory`
(Phase 2), единая секция `observability` + hot-reload watcher в оркестраторе (Phase 3). Документ
фиксирует, КАК будущие фичи подключаются к этому контуру **без переделки ядра** — следующий
разработчик дописывает по якорям, а не изобретает.

**Якоря (существующие контракты — НЕ менять):**
- `IChannel.write(record: dict) -> dict` — контракт любого sink (`channel_routing_module/interfaces.py`).
- `register_sink_factory(sink_type: str, factory: type) -> None` — реестр фабрик (`logger_module/channels/log_channel.py`).
- `ChannelRoutingManager.reconfigure(config: dict) -> bool` → хук `_rebuild_from_config(dict)` (full-rebuild).
- `expand_observability(dict) -> {"logger","error","stats"}` (`process_module/configs/observability_config.py`).
- `start_observability_watcher(*, config_path, logger, error, stats, ...)` (`process_module/managers/observability_reload.py`).
- Control plane: `BackendDriver` + `RouterManager.request/reply` + `introspect.*` (см. `backend-control-mcp`).

**Точки расширения:**

1. **SQLChannel** — (а) контракт `IChannel`/`LogChannel`; (б) якорь `class SqlChannel(LogChannel): def write(self, record: dict) -> dict`; (в) дописать класс + `register_sink_factory("sql", SqlChannel)` + секция `channels: {audit_sql: {type: sql, dsn: ...}}`; (г) НЕ требует правок менеджеров/`create_channel`/`reconfigure`. Refs: comm-system §12 P2/P3 (audit-log).
2. **SocketChannel-push** — (а) `IChannel`; (б) якорь `class SocketChannel(IChannel): write()` шлёт через `RouterManager` (Dict at Boundary, БЕЗ прямого SHM — `feedback_no_shm_hacks`); (в) дописать класс + `register_sink_factory("socket", ...)`; (г) ядро не трогается. Путь к cross-process remote-stats.
3. **IPC-команды → `reconfigure`** — (а) живой control plane (`BackendDriver`/`introspect.handlers`); (б) якоря команд: `config.reload` → `manager.reconfigure(new_dict)`; `logger.sink.enable` → `ObservableMixin.enable` / `register_channel`+`unregister_channel`; `stats.subscribe` → `register_sink_factory`+`register_channel` SocketChannel; (в) дописать handler'ы команд в PM (watcher уже в PM — Phase 4 добавляет IPC fan-out на детей); (г) `reconfigure`/реестр НЕ меняются. Refs: `backend-control-mcp`.
4. **GUI-вкладка** — (а) `get_stats()` / `get_registered_sink_types()` на чтение, IPC-команды (п.3) на запись; (б) якорь `LoggerManager.get_stats() -> dict`; (в) дописать вкладку; (г) НИКАКОГО прямого доступа к менеджерам из GUI (Dict at Boundary).
5. **cross-process remote-stats** — StatsManager получает router-ссылку + SocketChannel-sink. В Итерации 1 router намеренно НЕ держится (ADR comm-system §9.7) — это осознанный задел, не недоделка.

**Следствие:** все пять направлений — аддитивные (новый класс канала ИЛИ новый command-handler), ядро
(`reconfigure`, реестр, watcher) остаётся неизменным. Cross-process hot-reload = Phase 4 IPC поверх
watcher'а в PM (forward-compatible, без выбрасываемого кода).

**Refs:** `plans/2026-06-03_observability-control-plane/`, `plans/2026-05-31_comm-system-target-architecture` §12, `plans/.../backend-control-mcp`.
