# -*- coding: utf-8 -*-
"""TopologyContext — связка зависимостей топологии (pipeline graph).

Объединяет holder + bridge + command_catalog в единый узкий контракт.
Импортируется потребителями pipeline (presenter, inspector) вместо
полного AppContext.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge.command_catalog import CommandCatalog
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.frontend.topology_holder import TopologyHolder


@dataclass(frozen=True)
class TopologyContext:
    """Топология pipeline: holder + bridge + command_catalog.

    Attributes:
        holder: TopologyHolder (текущая topology dict + notify).
        bridge: TopologyBridge (мост GUI ↔ Runtime: field_set / state_delta).
        catalog: CommandCatalog (каталог IPC-команд из PluginRegistry).
    """

    holder: "TopologyHolder"
    bridge: "TopologyBridge | None" = None
    catalog: "CommandCatalog | None" = None
