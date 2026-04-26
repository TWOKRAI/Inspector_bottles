"""Параметры операции бинаризации кадра (threshold)."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("ThresholdParamsV3")
class ThresholdParams(ProcessingParamsBase):
    """Параметры операции пороговой бинаризации."""

    type: Literal["threshold"] = "threshold"

    thresh_value: Annotated[
        float,
        FieldMeta("Порог", info="Пороговое значение пикселя.", min=0.0, max=255.0),
    ] = 128.0

    max_value: Annotated[
        float,
        FieldMeta("Максимальное значение", info="Значение для пикселей выше порога.", min=0.0, max=255.0),
    ] = 255.0

    mode: Annotated[
        Literal["binary", "binary_inv", "trunc", "tozero", "otsu"],
        FieldMeta("Режим", info="cv2 threshold mode."),
    ] = "binary"


__all__ = ["ThresholdParams"]
