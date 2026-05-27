# -*- coding: utf-8 -*-
"""
adapters/stores/ — adapter'ы для persistence-хранилищ (topology, recipes, registers).

Публичный API:
    TopologyRepositoryFromHolder — bidirectional bridge domain.Topology <-> TopologyHolder.
    RegistersBackendFromManager — adapter поверх RegistersManager (Variant A: знает topology+catalog).
    RecipeStoreFromManager — bypass RecipeManager.save(), пишет YAML с denormalize meta→top-level.

Phase C/D: предназначен для wrapping legacy holders.
Phase F: holders будут удалены после полной миграции на EventBus.

Границы импортов:
    - Разрешено: domain/, multiprocess_framework/*, Services/*, Plugins/*,
                 multiprocess_prototype/* (кроме frontend)
    - ЗАПРЕЩЕНО: PySide6/Qt
    - ЗАПРЕЩЕНО: multiprocess_prototype.frontend.*
      (исключение: topology_holder.py как bridge-объект — задокументировано в decisions Q1)
"""

from __future__ import annotations

from .recipe_store import RecipeStoreFromManager
from .registers_backend import RegistersBackendFromManager
from .topology_repository import TopologyRepositoryFromHolder

__all__ = [
    "RecipeStoreFromManager",
    "RegistersBackendFromManager",
    "TopologyRepositoryFromHolder",
]
