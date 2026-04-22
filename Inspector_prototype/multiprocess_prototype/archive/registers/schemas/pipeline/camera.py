# -*- coding: utf-8 -*-
"""Логическая камера (источник) и набор регионов."""

from __future__ import annotations

from typing import Annotated, Dict

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from .region import Region


@register_schema("Camera")
class Camera(SchemaBase):
    """Логическая камера: набор имёнованных регионов."""

    enabled: Annotated[
        bool,
        FieldMeta("Камера активна", info="Если false — камера не используется."),
    ] = True
    regions: Dict[str, Region] = Field(default_factory=dict)
