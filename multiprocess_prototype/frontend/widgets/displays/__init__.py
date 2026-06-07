"""displays — пакет окон превью SHM-каналов дисплеев.

Публичный API:
    - ``PreviewWindow``        — автономное QWidget-окно с QLabel для кадров
    - ``open_for_display``     — фабрика: создаёт, подписывает, показывает
    - ``PreviewWindowManager`` — реестр открытых окон; управляет orphan/reconnect
"""

from .preview_manager import PreviewWindowManager
from .preview_window import PreviewWindow, open_for_display

__all__ = ["PreviewWindow", "open_for_display", "PreviewWindowManager"]
