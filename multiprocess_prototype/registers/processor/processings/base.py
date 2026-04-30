"""Base entities for processing algorithm parameters."""

from __future__ import annotations

from typing import Annotated, TYPE_CHECKING

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

if TYPE_CHECKING:
    from .params import ProcessorParams


class ProcessingParamsBase(SchemaBase):
    """Base for concrete algorithm parameter schemas."""


@register_schema("BaseProcessingBlockV3")
class BaseProcessingBlock(SchemaBase):
    """Base for all processing blocks inside a region."""

    enabled: Annotated[
        bool,
        FieldMeta("Включено", info="Учитывать ли блок в пайплайне."),
    ] = True
    params: "ProcessorParams" = Field(default_factory=lambda: _default_color_params())


def _default_color_params():
    from .color_detection import ColorDetectionParams
    return ColorDetectionParams()


__all__ = ["ProcessingParamsBase", "BaseProcessingBlock"]
