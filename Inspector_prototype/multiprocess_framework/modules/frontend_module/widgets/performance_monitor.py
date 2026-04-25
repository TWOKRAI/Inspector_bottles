# -*- coding: utf-8 -*-
"""
PerformanceMonitor — централизованное хранилище метрик производительности.
FPS, время обработки, размер изображения.
"""
from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QObject, pyqtSignal


class PerformanceMonitor(QObject):
    """Монитор производительности. Сигнал updated при изменении метрик."""
    updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fps_after_processing: float = 0.0
        self.processing_time_ms: float = 0.0
        self.total_time_ms: float = 0.0
        self.image_width: int = 0
        self.image_height: int = 0

    def update_metrics(self, fps: float, proc_time: float, total_time: float) -> None:
        self.fps_after_processing = fps
        self.processing_time_ms = proc_time
        self.total_time_ms = total_time
        self.updated.emit()

    def update_image_size(self, width: int, height: int) -> None:
        self.image_width = width
        self.image_height = height
        self.updated.emit()

    def reset(self) -> None:
        self.fps_after_processing = 0.0
        self.processing_time_ms = 0.0
        self.total_time_ms = 0.0
        self.image_width = 0
        self.image_height = 0
        self.updated.emit()
