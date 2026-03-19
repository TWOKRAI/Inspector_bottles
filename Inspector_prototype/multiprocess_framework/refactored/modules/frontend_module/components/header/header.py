# -*- coding: utf-8 -*-
"""
HeaderWidget — контейнер шапки приложения.

Композиция: LogoWidget, AdminButtonWidget, HeaderButtonsWidget.
Привязка при компоновке через сигналы:
  header.buttons_widget.button_clicked.connect(show_window)
  header.admin_button.clicked.connect(open_admin)
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from frontend_module.core.qt_imports import QHBoxLayout, QPixmap, QVBoxLayout, QWidget

from .admin_button_widget import AdminButtonWidget
from .header_buttons_widget import HeaderButtonsWidget
from .logo_widget import LogoWidget
from ..base.button_style import create_header_button


class HeaderWidget(QWidget):
    """
    Шапка — контейнер из LogoWidget, AdminButtonWidget, HeaderButtonsWidget.

    Публичные атрибуты:
      logo: LogoWidget
      admin_button: AdminButtonWidget
      buttons_widget: HeaderButtonsWidget (button_clicked = pyqtSignal(str))

    Конфиг: {logo: {...}, admin_button: {...}, windows: [...]}
    """

    def __init__(
        self,
        *,
        config: Optional[Dict[str, Any]] = None,
        on_fullscreen_toggle: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        cfg = config or {}
        logo_cfg = dict(cfg.get("logo", {}))
        admin_cfg = dict(cfg.get("admin_button", {}))
        windows_list = cfg.get("windows", [])

        self._logo_pixmap = cfg.get("logo_pixmap") or cfg.get("pixmap")
        self.logo = LogoWidget(config=logo_cfg, pixmap=self._logo_pixmap)
        self.admin_button = AdminButtonWidget(config=admin_cfg)
        self.buttons_widget = HeaderButtonsWidget(config=windows_list)

        self._on_fullscreen_toggle = on_fullscreen_toggle
        self._on_close = on_close
        self._init_ui()

    def _init_ui(self) -> None:
        self.all_layout = QVBoxLayout()
        self.all_layout.addSpacing(9)
        self.top_layout = QHBoxLayout()
        self.top_layout.addSpacing(5)

        # [Admin] [Buttons] [Stretch] [Logo]
        self.top_layout.addWidget(self.admin_button)
        self.top_layout.addSpacing(30)
        self.top_layout.addWidget(self.buttons_widget)
        if self._on_fullscreen_toggle is not None:
            fs_btn = create_header_button(label="ЭКРАН", on_click=self._on_fullscreen_toggle)
            self.top_layout.addWidget(fs_btn)
            self.top_layout.addSpacing(30)
        if self._on_close is not None:
            close_btn = create_header_button(label="ЗАКРЫТЬ", on_click=self._on_close)
            self.top_layout.addWidget(close_btn)
            self.top_layout.addSpacing(30)
        self.top_layout.addStretch()
        self.top_layout.addWidget(self.logo)
        self.top_layout.addSpacing(12)

        self.all_layout.addLayout(self.top_layout)
        self.setLayout(self.all_layout)

        if self._logo_pixmap:
            self.logo.set_pixmap(self._logo_pixmap)
