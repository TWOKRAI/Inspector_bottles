# -*- coding: utf-8 -*-
"""Обработки: базовый блок и разновидности параметров (multiprocess_prototype_v2.registers)."""

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
