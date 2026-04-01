# -*- coding: utf-8 -*-
"""Union параметров обработок (multiprocess_prototype_v2.registers)."""

from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field

from .base_processing import BaseProcessingBlock
from .blob_detection import BlobDetectionParams
from .color_detection import ColorDetectionParams


ProcessorParams = Annotated[
    Union[ColorDetectionParams, BlobDetectionParams],
    Field(discriminator="type"),
]

# Resolve forward reference "ProcessorParams" in BaseProcessingBlock.params.
BaseProcessingBlock.model_rebuild(_types_namespace={"ProcessorParams": ProcessorParams})
