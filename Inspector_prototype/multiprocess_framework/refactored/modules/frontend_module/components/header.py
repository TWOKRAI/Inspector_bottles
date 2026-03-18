# -*- coding: utf-8 -*-
"""
HeaderWidget — шапка приложения с кнопками и логотипом.
Порт с абстракцией: callbacks вместо прямых зависимостей.
"""
from __future__ import annotations

from typing import Callable, Optional

try:
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
    from PyQt5.QtGui import QImage, QPixmap, QIcon
    from PyQt5.QtCore import Qt, QSize, pyqtSignal
    _HAS_QT = True
except ImportError:
    _HAS_QT = False


if _HAS_QT:

    class ButtonHeader:
        width = 80
        height = 80
        icon_size = QSize(60, 60)
        pressed_icon_size = QSize(75, 75)

        def __init__(self) -> None:
            self.name = ''
            self.image = None
            self.func: Callable[[], None] = lambda: None
            self.init_ui()

        def init_ui(self):
            self.button = QPushButton()
            if self.name:
                self.button.setText(self.name)
            self.button.setMinimumSize(self.width, self.height)
            self.button.clicked.connect(self.func)
            if self.image:
                icon = QIcon(self.image)
                self.button.setIcon(icon)
                self.button.setIconSize(self.icon_size)
            self.button.pressed.connect(self.on_button_pressed)
            self.button.released.connect(self.on_button_released)
            self.button.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    font-size: 20px;
                }
                QPushButton:pressed {
                    font-size: 25px;
                }
            """)

        def on_button_pressed(self):
            self.button.setIconSize(self.pressed_icon_size)

        def on_button_released(self):
            self.button.setIconSize(self.icon_size)

        def update(self):
            self.init_ui()
            return self.button

    class HeaderWidget(QWidget):
        """Шапка с кнопками. Эмитит main_show, neuroun_show. Callbacks для остальных действий."""
        main_show = pyqtSignal()
        neuroun_show = pyqtSignal()

        def __init__(
            self,
            *,
            on_main_show: Optional[Callable[[], None]] = None,
            on_neuroun_show: Optional[Callable[[], None]] = None,
            on_fullscreen_toggle: Optional[Callable[[], None]] = None,
            on_close: Optional[Callable[[], None]] = None,
            on_admin: Optional[Callable[[], None]] = None,
            logo_path: Optional[str] = None,
            logo_pixmap: Optional[QPixmap] = None,
            parent=None,
        ):
            super().__init__(parent)
            self._on_main_show = on_main_show
            self._on_neuroun_show = on_neuroun_show
            self._on_fullscreen_toggle = on_fullscreen_toggle
            self._on_close = on_close
            self._on_admin = on_admin
            self._logo_path = logo_path
            self._logo_pixmap = logo_pixmap
            self.init_ui()

        def init_ui(self):
            self.all_layout = QVBoxLayout()
            self.all_layout.addSpacing(9)
            self.top_layout = QHBoxLayout()
            self.top_layout.addSpacing(5)
            layout_buttons = self.setup_buttons()
            self.top_layout.addLayout(layout_buttons)
            self.top_layout.addStretch()
            self.setup_logo()
            self.top_layout.addSpacing(12)
            self.all_layout.addLayout(self.top_layout)
            self.setLayout(self.all_layout)

        def setup_buttons(self):
            layout_buttons = QHBoxLayout()
            layout_buttons.addSpacing(50)
            if self._on_admin is not None:
                self.admin_button = ButtonHeader()
                self.admin_button.name = 'Admin'
                self.admin_button.func = self._on_admin
                layout_buttons.addWidget(self.admin_button.update())
                layout_buttons.addSpacing(30)
            self.home_button = ButtonHeader()
            self.home_button.name = 'Домой'
            self.home_button.func = self._show_home
            layout_buttons.addWidget(self.home_button.update())
            layout_buttons.addSpacing(30)
            self.neuroun_button = ButtonHeader()
            self.neuroun_button.name = 'Нейрон'
            self.neuroun_button.func = self._show_neuroun
            layout_buttons.addWidget(self.neuroun_button.update())
            layout_buttons.addSpacing(30)
            if self._on_fullscreen_toggle is not None:
                self.fullscreen_button = ButtonHeader()
                self.fullscreen_button.name = 'ЭКРАН'
                self.fullscreen_button.func = self._on_fullscreen_toggle
                layout_buttons.addWidget(self.fullscreen_button.update())
                layout_buttons.addSpacing(30)
            if self._on_close is not None:
                self.close_button = ButtonHeader()
                self.close_button.name = 'ЗАКРЫТЬ'
                self.close_button.func = self._on_close
                layout_buttons.addWidget(self.close_button.update())
                layout_buttons.addSpacing(30)
            return layout_buttons

        def _show_home(self):
            if self._on_main_show:
                self._on_main_show()
            else:
                self.main_show.emit()

        def _show_neuroun(self):
            if self._on_neuroun_show:
                self._on_neuroun_show()
            else:
                self.neuroun_show.emit()

        def setup_logo(self):
            layout_logo_v = QHBoxLayout()
            layout_logo_v.addStretch()
            top_image_label = QLabel()
            pixmap = None
            if self._logo_pixmap:
                pixmap = self._logo_pixmap
            elif self._logo_path:
                image = QImage(self._logo_path)
                if not image.isNull():
                    scaled = image.scaled(image.width() // 2, image.height() // 2, Qt.KeepAspectRatio)
                    pixmap = QPixmap.fromImage(scaled)
            if pixmap and not pixmap.isNull():
                top_image_label.setPixmap(pixmap)
            top_image_label.setAlignment(Qt.AlignCenter)
            top_image_label.setScaledContents(False)
            layout_logo_v.addWidget(top_image_label)
            layout_logo_v.addStretch()
            self.top_layout.addLayout(layout_logo_v)

else:
    ButtonHeader = None  # type: ignore
    HeaderWidget = None  # type: ignore
