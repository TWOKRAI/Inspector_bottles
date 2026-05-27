# -*- coding: utf-8 -*-
"""
domain/protocols/topology_repository.py — Protocol для persistence топологии.

TopologyRepository — минимальный синхронный контракт: load/save.
Подписки на изменения идут через EventBus (не через repository),
что сохраняет TopologyRepository минимальным и не размывает ответственность.

Phase C создаст адаптер TopologyRepositoryFromHolder поверх TopologyHolder.

Решение: EventBus vs TopologyRepository.subscribe() — зафиксировано в plans/
2026-05-27_cross-tab-architecture/phase-b-domain.md (Открытые вопросы).
Выбрано: EventBus. TopologyRepository остаётся чисто persistence.
"""

from __future__ import annotations

from typing import Protocol

from ..entities.topology import Topology


class TopologyRepository(Protocol):
    """Контракт синхронного persistence топологии.

    Реализации: TopologyRepositoryFromHolder (Phase C), _FakeTopologyRepository (тесты).
    """

    def load(self) -> Topology:
        """Загрузить текущую топологию."""
        ...

    def save(self, topology: Topology) -> None:
        """Сохранить топологию."""
        ...


__all__ = [
    "TopologyRepository",
]
