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
