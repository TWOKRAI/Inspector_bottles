# -*- coding: utf-8 -*-
"""frontend/topology_events.py — обвязка typed topology-событий (Phase G G.1).

Единый seam composition root: соединяет legacy TopologyHolder с typed EventBus,
чтобы UI-подписчики работали через domain-события, а не через holder.on_changed.

Поток:
    holder.set_topology(...) → holder.on_changed → publish(TopologyReplaced)
        → EventBus → подписчики (PipelinePresenter scene reload, TopologyBridge cache).

После G.1 единственный holder.on_changed-подписчик — publisher-мост отсюда.
G.3 заменит этот хук на публикацию в преемнике set_topology и удалит holder.

Вынесено из app.py в отдельный helper, чтобы обвязку можно было протестировать
на реальных компонентах (см. frontend/tests/test_topology_events_wiring.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_prototype.domain.events import TopologyReplaced

if TYPE_CHECKING:
    from multiprocess_prototype.domain.protocols.event_bus import EventBusProtocol


def wire_topology_events(
    holder: Any,
    events: "EventBusProtocol",
    topology_bridge: Any | None = None,
) -> None:
    """Подключить publisher-мост holder → EventBus и (опц.) подписку bridge.

    Args:
        holder: TopologyHolder (нужен .on_changed(callback)).
        events: EventBus (нужны .publish() / .subscribe()).
        topology_bridge: опц. TopologyBridge (нужен .on_topology_changed()) —
            подписывается на TopologyReplaced для инвалидации IPC-кэша.

    Post:
        holder.set_topology(...) публикует TopologyReplaced на events;
        если задан topology_bridge — он получает уведомление через events.
    """
    holder.on_changed(lambda _topology: events.publish(TopologyReplaced(reason="topology_changed")))
    if topology_bridge is not None:
        events.subscribe(TopologyReplaced, lambda _event: topology_bridge.on_topology_changed())
