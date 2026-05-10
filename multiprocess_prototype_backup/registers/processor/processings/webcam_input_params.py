"""Параметры операции захвата кадра с веб-камеры."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("WebcamInputParamsV3")
class WebcamInputParams(ProcessingParamsBase):
    """Параметры входной операции веб-камеры."""

    type: Literal["webcam_input"] = "webcam_input"

    width: Annotated[
        int,
        FieldMeta("Ширина", info="Запрашиваемая ширина кадра.", min=160, max=4096, unit="px"),
    ] = 640

    height: Annotated[
        int,
        FieldMeta("Высота", info="Запрашиваемая высота кадра.", min=120, max=2160, unit="px"),
    ] = 480

    device_id: Annotated[
        int,
        FieldMeta("Индекс устройства", info="Индекс камеры (0 — первая доступная).", min=0, max=15),
    ] = 0


__all__ = ["WebcamInputParams"]
