# -*- coding: utf-8 -*-
"""
ChannelRoutingManagerConfig — плоская схема для реестра/UI (только поля).

Рантайм-наследование менеджеров — от ``core/config.py: ChannelRoutingConfig``; см. ADR-108.
"""
from __future__ import annotations

from typing import Annotated, Dict

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("channel_routing_manager")
class ChannelRoutingManagerConfig(SchemaBase):
    """Каналы и имя менеджера — только поля; сборка через ``model_dump()`` / ``SchemaMixin.build()``."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "ChannelRoutingManager"
    channels: Annotated[
        Dict[str, dict],
        FieldMeta("Каналы: имя → параметры канала"),
    ] = {}
