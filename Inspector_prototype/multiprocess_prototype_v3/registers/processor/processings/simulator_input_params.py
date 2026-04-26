"""Параметры операции захвата кадра через симулятор."""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("SimulatorInputParamsV3")
class SimulatorInputParams(ProcessingParamsBase):
    """Параметры входной операции симулятора кадров."""

    type: Literal["simulator_input"] = "simulator_input"

    width: Annotated[
        int,
        FieldMeta("Ширина", info="Ширина генерируемого кадра.", min=160, max=4096, unit="px"),
    ] = 640

    height: Annotated[
        int,
        FieldMeta("Высота", info="Высота генерируемого кадра.", min=120, max=2160, unit="px"),
    ] = 480

    image_path: Annotated[
        Optional[str],
        FieldMeta("Путь к изображению", info="Путь к статичной картинке. None — генератор шума."),
    ] = None


__all__ = ["SimulatorInputParams"]
