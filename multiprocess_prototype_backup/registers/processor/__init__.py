"""Processor domain: detection schemas and algorithm parameters."""

from .processings import (
    BaseProcessingBlock,
    BlobDetectionParams,
    ColorDetectionParams,
    ProcessingParamsBase,
    ProcessorParams,
)
from .schemas import ProcessorRegisters

__all__ = [
    "ProcessorRegisters",
    "ProcessingParamsBase",
    "BaseProcessingBlock",
    "ColorDetectionParams",
    "BlobDetectionParams",
    "ProcessorParams",
]
