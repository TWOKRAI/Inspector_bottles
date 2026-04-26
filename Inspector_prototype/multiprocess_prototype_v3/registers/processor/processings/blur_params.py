"""Параметры операции размытия кадра (Gaussian Blur)."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("BlurParamsV3")
class BlurParams(ProcessingParamsBase):
    """Параметры операции гауссова размытия."""

    type: Literal["blur"] = "blur"

    kernel_size: Annotated[
        int,
        FieldMeta(
            "Размер ядра",
            info="Должен быть нечётным; чётный — увеличиваем на 1 в operation.",
            min=1,
            max=99,
        ),
    ] = 5

    sigma: Annotated[
        float,
        FieldMeta("Сигма", info="0 — авто из kernel_size.", min=0.0, max=50.0),
    ] = 0.0


__all__ = ["BlurParams"]
