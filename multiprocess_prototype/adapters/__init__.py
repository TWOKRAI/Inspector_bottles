# -*- coding: utf-8 -*-
"""
multiprocess_prototype.adapters — adapter-слой между domain Protocols и реальными реестрами.

Каждый adapter оборачивает singleton-реестр фреймворка и реализует
соответствующий domain Protocol из multiprocess_prototype.domain.protocols.

Текущий состав (Phase C):
    catalogs/ — PluginCatalogFromRegistry, ServiceManagerFromRegistry,
                DisplayCatalogFromRegistry

Phase D подключил эти adapters к AppServices через DI-контейнер.

Границы импортов (enforced):
    - Разрешено: domain/, multiprocess_framework/modules/*, Services/*, Plugins/*
    - ЗАПРЕЩЕНО: PySide6/Qt
    - ЗАПРЕЩЕНО: multiprocess_prototype.frontend.* (исключение: topology_holder.py
      как bridge-объект в TopologyRepositoryFromHolder — задокументировано в decisions Q1 Phase C)
"""

from __future__ import annotations

from .auth import AuthFacadeFromAuthState
from .catalogs import (
    DisplayCatalogFromRegistry,
    PluginCatalogFromRegistry,
    ServiceManagerFromRegistry,
)
from .dispatch import CommandDispatcherOrchestrator, ProjectHolder
from .stores import (
    ConfigStoreFromManager,
    RecipeStoreFromManager,
    RegistersBackendFromManager,
    TopologyRepositoryFromHolder,
)

__all__ = [
    "AuthFacadeFromAuthState",
    "PluginCatalogFromRegistry",
    "ServiceManagerFromRegistry",
    "DisplayCatalogFromRegistry",
    "TopologyRepositoryFromHolder",
    "RegistersBackendFromManager",
    "RecipeStoreFromManager",
    "ConfigStoreFromManager",
    "CommandDispatcherOrchestrator",
    "ProjectHolder",
]
