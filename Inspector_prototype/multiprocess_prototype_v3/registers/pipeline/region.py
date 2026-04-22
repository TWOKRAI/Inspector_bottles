"""Base ROI region schema (without nested processing blocks)."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from .rect import Rect


@register_schema("RegionV3")
class Region(SchemaBase):
    """Base ROI region without nested processing."""

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

    steps: Annotated[
        List[Dict[str, Any]],
        FieldMeta("Processing steps", info="Ordered list of processing step configs. Filled in Phase 5."),
    ] = Field(default_factory=list)


__all__ = ["Region"]
