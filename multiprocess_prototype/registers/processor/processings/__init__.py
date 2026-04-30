"""Processing algorithm schemas: color detection, blob detection, base block."""

from .base import BaseProcessingBlock, ProcessingParamsBase
from .blob_detection import BlobDetectionParams
from .color_detection import ColorDetectionParams
from .params import ProcessorParams

__all__ = [
    "ProcessingParamsBase",
    "BaseProcessingBlock",
    "ColorDetectionParams",
    "BlobDetectionParams",
    "ProcessorParams",
]
