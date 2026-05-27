# -*- coding: utf-8 -*-
"""
adapters/catalogs — read-only адаптеры для catalog-реестров фреймворка.

Экспортирует три адаптера, каждый из которых реализует соответствующий
domain Protocol из multiprocess_prototype.domain.protocols.

Классы:
    PluginCatalogFromRegistry  — _PluginRegistry  → PluginCatalog  Protocol
    ServiceCatalogFromRegistry — ServiceRegistry  → ServiceCatalog Protocol
    DisplayCatalogFromRegistry — DisplayRegistry  → DisplayCatalog Protocol
"""

from __future__ import annotations

from .display_catalog import DisplayCatalogFromRegistry
from .plugin_catalog import PluginCatalogFromRegistry
from .service_catalog import ServiceCatalogFromRegistry

__all__ = [
    "PluginCatalogFromRegistry",
    "ServiceCatalogFromRegistry",
    "DisplayCatalogFromRegistry",
]
