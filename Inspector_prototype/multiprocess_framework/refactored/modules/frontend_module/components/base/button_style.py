# -*- coding: utf-8 -*-
"""
Общие стили и фабрика кнопок для header-компонентов.
"""
from __future__ import annotations

from typing import Callable, Optional

from frontend_module.core.qt_imports import QPushButton, QSize, QWidget


class ButtonHeader:
    """Legacy: фабрика кнопок в стиле header. Используйте create_header_button."""

    width = 80
    height = 80
    icon_size = QSize(60, 60)
    pressed_icon_size = QSize(75, 75)

    def __init__(self) -> None:
        self.name = ""
        self.image = None
        self.func: Callable[[], None] = lambda: None

    def init_ui(self) -> QPushButton:
        btn = create_header_button(label=self.name, on_click=self.func, icon=self.image)
        return btn

    def update(self) -> QPushButton:
        return self.init_ui()


HEADER_BUTTON_WIDTH = 80
HEADER_BUTTON_HEIGHT = 80
HEADER_ICON_SIZE = QSize(60, 60)
HEADER_PRESSED_ICON_SIZE = QSize(75, 75)

HEADER_BUTTON_STYLESHEET = """
    QPushButton {
        background-color: transparent;
        border: none;
        font-size: 20px;
    }
    QPushButton:pressed {
        font-size: 25px;
    }
"""


def create_header_button(
    label: str = "",
    on_click: Optional[Callable[[], None]] = None,
    icon=None,
    parent: Optional[QWidget] = None,
) -> QPushButton:
    """Создать кнопку в стиле header."""
    btn = QPushButton(parent)
    if label:
        btn.setText(label)
    btn.setMinimumSize(HEADER_BUTTON_WIDTH, HEADER_BUTTON_HEIGHT)
    btn.setStyleSheet(HEADER_BUTTON_STYLESHEET)
    if on_click:
        btn.clicked.connect(on_click)
    if icon:
        from frontend_module.core.qt_imports import QIcon
        btn.setIcon(QIcon(icon))
        btn.setIconSize(HEADER_ICON_SIZE)
        btn.pressed.connect(lambda: btn.setIconSize(HEADER_PRESSED_ICON_SIZE))
        btn.released.connect(lambda: btn.setIconSize(HEADER_ICON_SIZE))
    return btn
