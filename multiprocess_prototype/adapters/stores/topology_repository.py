# -*- coding: utf-8 -*-
"""
adapters/stores/topology_repository.py — bidirectional bridge domain.Topology <-> TopologyHolder.

TopologyRepositoryFromHolder реализует Protocol TopologyRepository из domain/protocols/.

Решение Q1 (закрыто 2026-05-27): Project = source of truth в Phase D+.
На уровне Phase C — bidirectional bridge без переноса state в Project.
save() пишет в holder; legacy callbacks вызываются по умолчанию.

Решение Q6 (закрыто 2026-05-27): suppress_legacy_notify() cm реализуется здесь
как toggle-флаг holder._suppress_notify — НЕ применяется по умолчанию.
Dispatcher (C.6) вызывает save() штатно, двойная нотификация — осознанный компромисс Phase D/E.
suppress_legacy_notify() активируется в Phase F после миграции всех подписчиков на EventBus.

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.3)
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.frontend.topology_holder import TopologyHolder


class TopologyRepositoryFromHolder:
    """Bidirectional bridge: domain.Topology <-> runtime TopologyHolder.

    Phase C+D: legacy holder.on_changed callbacks вызываются при save() по умолчанию.
    Это осознанный компромисс (двойная нотификация legacy + EventBus) — подробнее
    в decisions log Q7 Phase C.

    Phase F: suppress_legacy_notify() активируется после миграции всех подписчиков
    holder.on_changed на чистый EventBus, после чего holder может быть удалён.

    Известный компромисс: adapter импортирует frontend.topology_holder напрямую.
    Это исключение из правила «adapters не импортируют frontend», зафиксированное
    в decisions log Q1. Holder является bridge-объектом между GUI-слоем и domain.
    Удаление зависимости — Phase F.
    """

    def __init__(self, holder: TopologyHolder) -> None:
        self._holder = holder

    def load(self) -> Topology:
        """Загрузить текущую топологию из holder и вернуть как domain entity.

        Если holder пустой ({}), возвращает Topology с пустыми коллекциями.
        """
        return Topology.from_dict(self._holder.topology)

    def save(self, topology: Topology) -> None:
        """Сохранить domain Topology в holder, что триггерит legacy on_changed callbacks.

        По умолчанию callbacks вызываются. Для подавления callbacks
        использовать suppress_legacy_notify() context manager.
        """
        self._holder.set_topology(topology.to_dict())

    @contextlib.contextmanager
    def suppress_legacy_notify(self) -> Iterator[None]:
        """Временная мера до Phase F: подавить legacy holder.on_changed callbacks.

        Используется когда нужно записать топологию в holder без
        триггера UI-обновлений (например, при синхронизации из EventBus,
        чтобы избежать двойного обновления).

        Recursive use не поддерживается (single-thread Qt GUI предположение).
        Подавление снимается автоматически при выходе из блока with.

        Usage::

            with repo.suppress_legacy_notify():
                repo.save(new_topology)  # callbacks подавлены
            # после выхода callbacks работают нормально

        Refs: decisions log Q6/Q7, Phase C.
        """
        self._holder._suppress_notify = True
        try:
            yield
        finally:
            self._holder._suppress_notify = False
