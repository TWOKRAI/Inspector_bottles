# -*- coding: utf-8 -*-
"""Region (ROI) inside camera."""

from __future__ import annotations

from typing import Annotated, Dict

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from .processing_block import ProcessingBlock
from .rect import Rect


@register_schema("Region")
class Region(SchemaBase):
    """ROI: rectangle, flags, named processing blocks."""

    rect: Rect = Field(default_factory=Rect)
    enabled: Annotated[
        bool,
        FieldMeta("Region active", info="If false region is skipped."),
    ] = True
    is_main: Annotated[
        bool,
        FieldMeta("Main view", info="Main region for post-processing UI."),
    ] = False
    processing_enabled: Annotated[
        bool,
        FieldMeta("Processing enabled", info="Enable processing chain for this ROI."),
    ] = True
    sort_order: Annotated[
        int,
        FieldMeta("Order", info="Order in post-processing table (lower first)."),
    ] = 0
    processing: Dict[str, ProcessingBlock] = Field(default_factory=dict)
