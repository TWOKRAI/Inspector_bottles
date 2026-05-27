# -*- coding: utf-8 -*-
"""
adapters/catalogs — адаптеры для catalog-реестров фреймворка.

Экспортирует три адаптера, каждый из которых реализует соответствующий
domain Protocol из multiprocess_prototype.domain.protocols.

Классы:
    PluginCatalogFromRegistry   — _PluginRegistry  → PluginCatalog  Protocol
    ServiceManagerFromRegistry  — ServiceRegistry  → ServiceManager Protocol
    ServiceCatalogFromRegistry  — backward-compatible alias для ServiceManagerFromRegistry
    DisplayCatalogFromRegistry  — DisplayRegistry  → DisplayCatalog Protocol
"""

from __future__ import annotations

from .display_catalog import DisplayCatalogFromRegistry
from .plugin_catalog import PluginCatalogFromRegistry
from .service_catalog import ServiceCatalogFromRegistry, ServiceManagerFromRegistry

__all__ = [
    "PluginCatalogFromRegistry",
    "ServiceManagerFromRegistry",
    "ServiceCatalogFromRegistry",
    "DisplayCatalogFromRegistry",
]
