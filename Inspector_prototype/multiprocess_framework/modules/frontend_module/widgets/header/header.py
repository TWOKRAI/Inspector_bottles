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

from frontend_module.core.qt_imports import QHBoxLayout, QPixmap, QVBoxLayout, QWidget, pyqtSignal

from .admin_button_widget import AdminButtonConfig, AdminButtonWidget
from .header_buttons_widget import HeaderButtonsWidget
from .logo_widget import LogoWidget
from .button_style import create_header_button


class HeaderWidget(QWidget):
    """
    Шапка — контейнер из LogoWidget, AdminButtonWidget, HeaderButtonsWidget.

    Публичные атрибуты:
      logo: LogoWidget
      admin_button: AdminButtonWidget
      buttons_widget: HeaderButtonsWidget (button_clicked = pyqtSignal(str))
      action_triggered: pyqtSignal(str) — единый канал: id кнопок навигации + admin (action_id)

    Привязка: connect_action_handlers(action_triggered, handlers=..., on_unmatched=...)
    или get_signal_map() для интроспекции (ISignalProvider).

    Конфиг: {logo: {...}, admin_button: {...}, windows: [...]}
    """

    action_triggered = pyqtSignal(str)

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

        admin_model = (
            AdminButtonConfig(**admin_cfg) if isinstance(admin_cfg, dict) else (admin_cfg or AdminButtonConfig())
        )
        self._admin_action_id = admin_model.action_id

        self._logo_pixmap = cfg.get("logo_pixmap") or cfg.get("pixmap")
        self.logo = LogoWidget(config=logo_cfg, pixmap=self._logo_pixmap)
        self.admin_button = AdminButtonWidget(config=admin_model)
        self.buttons_widget = HeaderButtonsWidget(config=windows_list)

        self.buttons_widget.button_clicked.connect(self.action_triggered.emit)
        self.admin_button.clicked.connect(lambda: self.action_triggered.emit(self._admin_action_id))

        self._on_fullscreen_toggle = on_fullscreen_toggle
        self._on_close = on_close
        self._init_ui()

    def get_signal_map(self) -> Dict[str, Any]:
        """Каталог сигналов для подключения по конфигу (ISignalProvider)."""
        return {
            "action_triggered": self.action_triggered,
            "header_button_clicked": self.buttons_widget.button_clicked,
            "admin_clicked": self.admin_button.clicked,
        }

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
