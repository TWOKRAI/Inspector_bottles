# -*- coding: utf-8 -*-
"""
HeaderWidget — шапка приложения с кнопками и логотипом.
Порт с абстракцией: callbacks вместо прямых зависимостей.
Кнопки переключения окон создаются динамически из config["header"]["windows"].
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from frontend_module.core.qt_imports import (
    QHBoxLayout,
    QIcon,
    QImage,
    QLabel,
    QPixmap,
    QPushButton,
    QSize,
    QVBoxLayout,
    QWidget,
    Qt,
    pyqtSignal,
)


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
    """Шапка с кнопками. Кнопки переключения окон строятся из windows config."""
    main_show = pyqtSignal()
    neuroun_show = pyqtSignal()

    def __init__(
            self,
            *,
            windows: Optional[List[Dict[str, Any]]] = None,
            callbacks: Optional[Dict[str, Callable[[], None]]] = None,
            on_main_show: Optional[Callable[[], None]] = None,
            on_neuroun_show: Optional[Callable[[], None]] = None,
            on_fullscreen_toggle: Optional[Callable[[], None]] = None,
            on_close: Optional[Callable[[], None]] = None,
            on_admin: Optional[Callable[[], None]] = None,
            logo_path: Optional[str] = None,
            logo_pixmap: Optional[QPixmap] = None,
            show_admin: bool = True,
            parent=None,
    ):
        super().__init__(parent)
        self._windows = windows or [
            {"id": "main", "label": "Домой", "callback_key": "on_main_show"},
            {"id": "neuroun", "label": "Нейрон", "callback_key": "on_neuroun_show"},
        ]
        self._callbacks = dict(callbacks) if callbacks else {}
        if on_main_show is not None:
            self._callbacks["on_main_show"] = on_main_show
        if on_neuroun_show is not None:
            self._callbacks["on_neuroun_show"] = on_neuroun_show
        self._on_fullscreen_toggle = on_fullscreen_toggle
        self._on_close = on_close
        self._on_admin = on_admin
        self._logo_path = logo_path
        self._logo_pixmap = logo_pixmap
        self._show_admin = show_admin
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
        if self._show_admin and self._on_admin is not None:
            admin_btn = ButtonHeader()
            admin_btn.name = 'Admin'
            admin_btn.func = self._on_admin
            layout_buttons.addWidget(admin_btn.update())
            layout_buttons.addSpacing(30)
        for win_cfg in self._windows:
            btn = ButtonHeader()
            btn.name = win_cfg.get("label", win_cfg.get("id", ""))
            callback_key = win_cfg.get("callback_key")
            if callback_key and callback_key in self._callbacks:
                btn.func = self._callbacks[callback_key]
            else:
                btn.func = self._make_window_callback(win_cfg.get("id"))
            layout_buttons.addWidget(btn.update())
            layout_buttons.addSpacing(30)
        if self._on_fullscreen_toggle is not None:
            fs_btn = ButtonHeader()
            fs_btn.name = 'ЭКРАН'
            fs_btn.func = self._on_fullscreen_toggle
            layout_buttons.addWidget(fs_btn.update())
            layout_buttons.addSpacing(30)
        if self._on_close is not None:
            close_btn = ButtonHeader()
            close_btn.name = 'ЗАКРЫТЬ'
            close_btn.func = self._on_close
            layout_buttons.addWidget(close_btn.update())
            layout_buttons.addSpacing(30)
        return layout_buttons

    def _make_window_callback(self, window_id: str) -> Callable[[], None]:
        """Создать callback для переключения на окно (fallback на сигналы)."""
        def _cb() -> None:
            key = f"on_{window_id}_show" if window_id else "on_main_show"
            if key in self._callbacks:
                self._callbacks[key]()
            elif window_id == "main":
                self.main_show.emit()
            elif window_id == "neuroun":
                self.neuroun_show.emit()
        return _cb

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
