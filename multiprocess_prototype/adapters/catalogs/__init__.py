# -*- coding: utf-8 -*-
"""
adapters/catalogs — адаптеры для catalog-реестров фреймворка.

Экспортирует адаптеры, каждый из которых реализует соответствующий
domain Protocol из multiprocess_prototype.domain.protocols.

Классы:
    PluginCatalogFromRegistry   — _PluginRegistry  → PluginCatalog  Protocol
    ServiceManagerFromRegistry  — ServiceRegistry  → ServiceManager Protocol
    RemoteServiceManager        — хаб service.*    → ServiceManager Protocol (Task 1b.5)
    DisplayCatalogFromRegistry  — DisplayRegistry  → DisplayCatalog Protocol (registry-backed)
    DisplayCatalogFromRecipe    — RecipeStore      → DisplayCatalog Protocol (recipe-scoped)
"""

from __future__ import annotations

from .display_catalog import DisplayCatalogFromRegistry
from .display_catalog_recipe import DisplayCatalogFromRecipe
from .plugin_catalog import PluginCatalogFromRegistry
from .remote_service_manager import RemoteServiceManager
from .service_catalog import ServiceManagerFromRegistry

__all__ = [
    "PluginCatalogFromRegistry",
    "ServiceManagerFromRegistry",
    "RemoteServiceManager",
    "DisplayCatalogFromRegistry",
    "DisplayCatalogFromRecipe",
]
