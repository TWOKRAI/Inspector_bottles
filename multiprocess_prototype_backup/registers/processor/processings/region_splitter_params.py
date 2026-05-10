"""Параметры операции разделения кадра на регионы."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("RegionRectV3")
class RegionRect(ProcessingParamsBase):
    """Прямоугольный регион для сплита кадра."""

    name: Annotated[
        str,
        FieldMeta("Имя региона", info="Уникальное имя региона — используется как суффикс выходного порта."),
    ] = ""

    x: Annotated[
        int,
        FieldMeta("X", info="Левая координата региона (пиксели).", min=0, max=16384, unit="px"),
    ] = 0

    y: Annotated[
        int,
        FieldMeta("Y", info="Верхняя координата региона (пиксели).", min=0, max=16384, unit="px"),
    ] = 0

    width: Annotated[
        int,
        FieldMeta("Ширина", info="Ширина региона (пиксели).", min=0, max=16384, unit="px"),
    ] = 0

    height: Annotated[
        int,
        FieldMeta("Высота", info="Высота региона (пиксели).", min=0, max=16384, unit="px"),
    ] = 0


@register_schema("RegionSplitterParamsV3")
class RegionSplitterParams(ProcessingParamsBase):
    """Параметры операции динамического сплита кадра на N регионов."""

    type: Literal["region_splitter"] = "region_splitter"

    regions: Annotated[
        list[RegionRect],
        FieldMeta("Регионы", info="Список регионов 1→N для динамического сплита."),
    ] = []


__all__ = ["RegionRect", "RegionSplitterParams"]
