"""Параметры операции захвата кадра с камеры Hikvision."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("HikvisionInputParamsV3")
class HikvisionInputParams(ProcessingParamsBase):
    """Параметры входной операции камеры Hikvision."""

    type: Literal["hikvision_input"] = "hikvision_input"

    camera_index: Annotated[
        int,
        FieldMeta("Индекс камеры", info="Индекс камеры Hikvision в SDK.", min=0, max=15),
    ] = 0

    target_width: Annotated[
        int,
        FieldMeta("Целевая ширина", info="Ширина после ресайза.", min=160, max=4096, unit="px"),
    ] = 1920

    target_height: Annotated[
        int,
        FieldMeta("Целевая высота", info="Высота после ресайза.", min=120, max=2160, unit="px"),
    ] = 1080


__all__ = ["HikvisionInputParams"]
