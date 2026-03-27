# -*- coding: utf-8 -*-
"""Базовые сущности параметров обработок для schema_v3."""

from __future__ import annotations

from typing import Annotated, TYPE_CHECKING

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    SchemaBase,
    register_schema,
)

if TYPE_CHECKING:
    from .processing_params import ProcessorParams

PIPELINE_PARAMS_ROUTING = FieldRouting(channel="control_processor")


class ProcessingParamsBase(SchemaBase):
    """База для параметров конкретных алгоритмов."""


@register_schema("BaseProcessingBlockV3")
class BaseProcessingBlock(SchemaBase):
    """База для всех блоков обработки в регионе."""

    enabled: Annotated[
        bool,
        FieldMeta("Включено", info="Учитывать ли блок в пайплайне."),
    ] = True
    params: "ProcessorParams" = Field(default_factory=lambda: _default_color_params())


def _default_color_params():
    from .color_detection import ColorDetectionParams

    return ColorDetectionParams()
