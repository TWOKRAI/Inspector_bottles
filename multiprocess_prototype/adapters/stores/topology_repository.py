# -*- coding: utf-8 -*-
"""
adapters/stores/topology_repository.py — TopologyRepositoryStore: единый источник topology.

TopologyRepositoryStore владеет текущим topology dict и реализует domain Protocol
TopologyRepository (load/save). При каждой мутации публикует domain-событие
TopologyReplaced через injected EventBus — подписчики (PipelinePresenter scene reload,
TopologyBridge cache invalidation) реагируют через services.events, без прямого
доступа к store.

Store объединяет роли бывшего TopologyHolder (mutable dict + уведомления) и
domain-репозитория. Он удовлетворяет трём интерфейсам своих потребителей:
  - domain TopologyRepository Protocol: load() -> Topology, save(Topology) -> None;
  - framework TopologyHolderProtocol: set_topology(dict) -> None (ActionBus handlers);
  - IBridgeTopologyHolder: .topology property (TopologyBridge reads).

save() делегирует в set_topology() → ровно одна публикация TopologyReplaced на мутацию.

История (G.3, cross-tab-architecture): заменил TopologyRepositoryFromHolder +
frontend.topology_holder.TopologyHolder + topology_events.wire_topology_events
(publisher-мост) + suppress_legacy_notify. Adapters больше не импортируют frontend
(закрыто Q1-исключение Phase C).

Границы импортов: только domain (entities, events, protocols). frontend/Qt — запрещены.

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.3.1)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.events import TopologyReplaced

if TYPE_CHECKING:
    from multiprocess_prototype.domain.protocols.event_bus import EventBusProtocol


class TopologyRepositoryStore:
    """Источник истины topology: владеет dict, публикует TopologyReplaced на мутацию.

    Thread-safety: НЕ потокобезопасен — вызывать только из Qt main thread
    (QtEventBus публикует синхронно на main thread).
    """

    def __init__(self, initial: dict[str, Any] | None, events: "EventBusProtocol") -> None:
        """Args:
        initial: начальный topology dict (например, из blueprint). None → пустой.
        events: EventBus для публикации TopologyReplaced при мутациях.
        """
        self._topology: dict[str, Any] = initial or {}
        self._events = events
        # Мемоизация разобранной domain-Topology: load() дёргается ДЕСЯТКИ раз на
        # открытии вкладки (presenter: get_processes/is_protected/get_workers на
        # каждую панель/кнопку), а Topology.from_dict() — полный Pydantic-разбор
        # (8 процессов × плагины/воркеры). Кэш парсится один раз и живёт, пока dict
        # не сменится (set_topology инвалидирует). Topology — frozen (immutable),
        # общий инстанс безопасно отдавать read-only потребителям.
        self._cached: Topology | None = None

    @property
    def topology(self) -> dict[str, Any]:
        """Текущий topology dict (ссылка, не копия — для IPC-чтений TopologyBridge)."""
        return self._topology

    def load(self) -> Topology:
        """Загрузить текущую топологию как domain entity (пустой dict → пустая Topology).

        Мемоизировано: разбор ``from_dict`` выполняется один раз на версию dict'а
        (инвалидация — в ``set_topology``). Снимает O(N вызовов) Pydantic-разборов
        при построении вкладок (например Processes).
        """
        if self._cached is None:
            self._cached = Topology.from_dict(self._topology)
        return self._cached

    def save(self, topology: Topology) -> None:
        """Сохранить domain Topology. Публикует TopologyReplaced (через set_topology)."""
        self.set_topology(topology.to_dict())

    def set_topology(self, new_topology: dict[str, Any]) -> None:
        """Заменить topology dict и опубликовать TopologyReplaced.

        Интерфейс для framework TopologyHolderProtocol (ActionBus handlers) —
        принимает raw dict, возвращает None. Публикация синхронна на main thread.
        """
        self._topology = new_topology
        self._cached = None  # инвалидация мемо: следующий load() пересоберёт Topology
        self._events.publish(TopologyReplaced(reason="topology_changed"))


__all__ = [
    "TopologyRepositoryStore",
]
