"""ROI rectangle schema (x, y, width, height)."""

from __future__ import annotations

from typing import Annotated, List

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("RectV3")
class Rect(SchemaBase):
    """ROI rectangle (x, y, width, height)."""

    x: Annotated[int, FieldMeta("X", info="Левый верхний угол X", min=0.0, max=4096.0)] = 0
    y: Annotated[int, FieldMeta("Y", info="Левый верхний угол Y", min=0.0, max=4096.0)] = 0
    width: Annotated[int, FieldMeta("Ширина", info="Ширина ROI", min=0.0, max=4096.0)] = 0
    height: Annotated[int, FieldMeta("Высота", info="Высота ROI", min=0.0, max=4096.0)] = 0

    def to_coords_list(self) -> List[int]:
        return [self.x, self.y, self.width, self.height]

    @classmethod
    def from_coords_list(cls, coords: List[int]) -> "Rect":
        c = (coords + [0, 0, 0, 0])[:4]
        return cls(x=max(0, int(c[0])), y=max(0, int(c[1])), width=max(0, int(c[2])), height=max(0, int(c[3])))


__all__ = ["Rect"]
