# -*- coding: utf-8 -*-
"""Блок обработки внутри региона."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from .processing_params import ColorDetectionParams, ProcessorParams


@register_schema("ProcessingBlock")
class ProcessingBlock(SchemaBase):
    """Включённость и параметры одной обработки внутри региона."""

    enabled: Annotated[
        bool,
        FieldMeta("Включено", info="Учитывать ли блок в пайплайне."),
    ] = True
    params: ProcessorParams = Field(default_factory=ColorDetectionParams)
