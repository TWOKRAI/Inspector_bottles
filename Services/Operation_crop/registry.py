"""
Реестр обработчиков. Новый класс — добавить сюда.
"""

from typing import Dict, Type
from .base import BaseProcessor
from .processors.grayscale import GrayscaleProcessor
from .processors.blur import BlurProcessor
from .processors.canny import CannyProcessor
from .processors.threshold import ThresholdProcessor
from .processors.detect_horizontal_lines import DetectHorizontalLinesProcessor

REGISTRY: Dict[str, Type[BaseProcessor]] = {
    "grayscale": GrayscaleProcessor,
    "blur": BlurProcessor,
    "canny": CannyProcessor,
    "threshold": ThresholdProcessor,
    "detect_horizontal_lines": DetectHorizontalLinesProcessor,
}
