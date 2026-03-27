# -*- coding: utf-8 -*-
"""Обработки schema_v3: базовый блок и разновидности параметров."""

from .blob_detection import BlobDetectionParams
from .color_detection import ColorDetectionParams
from .base_processing import BaseProcessingBlock
from .processing_params import ProcessorParams

__all__ = [
    "BaseProcessingBlock",
    "ProcessorParams",
    "ColorDetectionParams",
    "BlobDetectionParams",
]
