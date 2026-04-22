"""Виджет display-окна для отображения видео-источника."""
from .widget import DisplayWindow
from .schemas import DisplayWindowConfig
from .source_selector import SourceSelectorCombo

__all__ = ["DisplayWindow", "DisplayWindowConfig", "SourceSelectorCombo"]
