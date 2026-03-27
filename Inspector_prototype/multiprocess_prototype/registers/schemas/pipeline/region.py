# -*- coding: utf-8 -*-
"""Region (ROI) inside camera."""

from __future__ import annotations

from typing import Annotated, Dict, List
from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from .processing_block import ProcessingBlock

@register_schema("Rect")
class Rect(SchemaBase):
    """Прямоугольник ROI (x, y, width, height)."""

    x: Annotated[
        int,
        FieldMeta("X", info="Левый верхний угол X", min=0.0, max=4096.0),
    ] = 0
    y: Annotated[
        int,
        FieldMeta("Y", info="Левый верхний угол Y", min=0.0, max=4096.0),
    ] = 0
    width: Annotated[
        int,
        FieldMeta("Ширина", info="Ширина ROI", min=0.0, max=4096.0),
    ] = 0
    height: Annotated[
        int,
        FieldMeta("Высота", info="Высота ROI", min=0.0, max=4096.0),
    ] = 0

    def to_coords_list(self) -> List[int]:
        """Формат совместимый с processor.crop_regions (список из четырёх int)."""
        return [self.x, self.y, self.width, self.height]

    @classmethod
    def from_coords_list(cls, coords: List[int]) -> Rect:
        c = (coords + [0, 0, 0, 0])[:4]
        return cls(
            x=max(0, int(c[0])),
            y=max(0, int(c[1])),
            width=max(0, int(c[2])),
            height=max(0, int(c[3])),
        )


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
