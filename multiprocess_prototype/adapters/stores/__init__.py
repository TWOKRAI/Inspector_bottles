# -*- coding: utf-8 -*-
"""
adapters/stores/ — adapter'ы для persistence-хранилищ (topology, recipes, registers).

Публичный API:
    TopologyRepositoryFromHolder — bidirectional bridge domain.Topology <-> TopologyHolder.

Phase C/D: предназначен для wrapping legacy holders.
Phase F: holders будут удалены после полной миграции на EventBus.

Границы импортов:
    - Разрешено: domain/, multiprocess_framework/*, Services/*, Plugins/*,
                 multiprocess_prototype/* (кроме frontend)
    - ЗАПРЕЩЕНО: PySide6/Qt
    - ЗАПРЕЩЕНО: multiprocess_prototype.frontend.*
"""

from __future__ import annotations

from .topology_repository import TopologyRepositoryFromHolder

__all__ = [
    "TopologyRepositoryFromHolder",
]
