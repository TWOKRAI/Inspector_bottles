# -*- coding: utf-8 -*-
"""
multiprocess_prototype.adapters — adapter-слой между domain Protocols и реальными реестрами.

Каждый adapter оборачивает singleton-реестр фреймворка и реализует
соответствующий domain Protocol из multiprocess_prototype.domain.protocols.

Текущий состав (Phase C):
    catalogs/ — PluginCatalogFromRegistry, ServiceCatalogFromRegistry, DisplayCatalogFromRegistry

Phase D подключит эти adapters к AppServices через DI-контейнер.

Границы импортов (enforced):
    - Разрешено: domain/, multiprocess_framework/modules/*, Services/*, Plugins/*
    - ЗАПРЕЩЕНО: PySide6/Qt
    - ЗАПРЕЩЕНО: multiprocess_prototype.frontend.*
"""

from __future__ import annotations

from .catalogs import DisplayCatalogFromRegistry, PluginCatalogFromRegistry, ServiceCatalogFromRegistry

__all__ = [
    "PluginCatalogFromRegistry",
    "ServiceCatalogFromRegistry",
    "DisplayCatalogFromRegistry",
]
