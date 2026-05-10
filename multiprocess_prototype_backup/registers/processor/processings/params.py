"""Union type for all processing algorithm parameter schemas."""

from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field

from .base import BaseProcessingBlock
from .blob_detection import BlobDetectionParams
from .color_detection import ColorDetectionParams

ProcessorParams = Annotated[
    Union[ColorDetectionParams, BlobDetectionParams],
    Field(discriminator="type"),
]

# Resolve forward reference "ProcessorParams" in BaseProcessingBlock.params.
BaseProcessingBlock.model_rebuild(_types_namespace={"ProcessorParams": ProcessorParams})

__all__ = ["ProcessorParams"]
