# -*- coding: utf-8 -*-
"""
adapters/stores/ — adapter'ы для persistence-хранилищ (topology, recipes, registers, config).

Публичный API:
    TopologyRepositoryStore — источник истины topology (владеет dict, публикует TopologyReplaced).
    RegistersBackendFromManager — adapter поверх RegistersManager (Variant A: знает topology+catalog).
    RecipeStoreFromManager — bypass RecipeManager.save(), пишет YAML с denormalize meta→top-level.
    ConfigStoreFromManager — adapter поверх config_module.Config (Task D.2b).

G.3: TopologyRepositoryStore заменил TopologyRepositoryFromHolder + TopologyHolder —
adapters больше не импортируют frontend (Q1-исключение закрыто).

Границы импортов:
    - Разрешено: domain/, multiprocess_framework/*, Services/*, Plugins/*,
                 multiprocess_prototype/* (кроме frontend)
    - ЗАПРЕЩЕНО: PySide6/Qt
    - ЗАПРЕЩЕНО: multiprocess_prototype.frontend.*
"""

from __future__ import annotations

from .config_store import ConfigStoreFromManager
from .recipe_store import RecipeStoreFromManager
from .registers_backend import RegistersBackendFromManager
from .topology_repository import TopologyRepositoryStore

__all__ = [
    "ConfigStoreFromManager",
    "RecipeStoreFromManager",
    "RegistersBackendFromManager",
    "TopologyRepositoryStore",
]
