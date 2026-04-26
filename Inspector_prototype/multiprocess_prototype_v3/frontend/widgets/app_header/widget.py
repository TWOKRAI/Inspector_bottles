# multiprocess_prototype_v3/frontend/widgets/app_header/widget.py
"""
AppHeaderWidget — кастомная шапка прототипа.

Композиция:
- слева: HeaderModeToggle + QLabel «INNOTECH»
- центр: QStackedWidget [info-страница (ticker + status_strip) | окно-кнопки]
- справа: кнопка «Сброс аварии» (без логики)

API совместим с framework HeaderWidget:
- сигнал `action_triggered: Signal(str)` (для connect_action_handlers)
- layout() — внешний QVBoxLayout, в него можно добавлять под-toolbar (undo/redo)
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    Signal,
)
from multiprocess_framework.modules.frontend_module.widgets.header.header_buttons_widget import (
    HeaderButtonsWidget,
)

from ..settings_tab.prefs_store import KEY_HEADER_MODE, get_view_mode, set_view_mode
from .info_ticker import InfoTickerWidget
from .mode_toggle import HeaderModeToggle
from .status_strip import StatusStripWidget

_BRAND_DEFAULT = "INNOTECH"


class AppHeaderWidget(QWidget):
    """Шапка приложения. Конфиг dict: {windows: [...], brand_text: str}."""

    action_triggered = Signal(str)

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        cfg = config or {}
        windows_list = cfg.get("windows", [])
        brand_text = cfg.get("brand_text") or _BRAND_DEFAULT

        self._mode_toggle = HeaderModeToggle(initial=get_view_mode(KEY_HEADER_MODE, default=0))
        self._brand_label = QLabel(brand_text)
        self._brand_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ddd;")

        # Режим A: бегущая строка + строка статусов
        self._info_ticker = InfoTickerWidget("")
        self._status_strip = StatusStripWidget()
        info_page = QWidget()
        info_v = QVBoxLayout(info_page)
        info_v.setContentsMargins(0, 0, 0, 0)
        info_v.setSpacing(2)
        info_v.addWidget(self._info_ticker)
        info_v.addWidget(self._status_strip)

        # Режим B: кнопки переключения окон
        self._buttons_widget = HeaderButtonsWidget(config=windows_list)
        self._buttons_widget.button_clicked.connect(self.action_triggered.emit)

        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(info_page)        # 0
        self._mode_stack.addWidget(self._buttons_widget)  # 1
        self._mode_stack.setCurrentIndex(self._mode_toggle.isChecked() and 1 or 0)

        # Кнопка «Сброс аварии» (без логики)
        self._reset_alarm_btn = QPushButton("Сброс аварии")
        self._reset_alarm_btn.setFixedHeight(36)
        self._reset_alarm_btn.setToolTip("Сброс аварии (TODO)")

        self._mode_toggle.mode_changed.connect(self._on_mode_changed)

        self._build_layout()

    def _build_layout(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(8, 0, 8, 0)
        top.setSpacing(6)

        # Слот для левых action-виджетов (undo/redo и т.п.)
        self._left_actions = QHBoxLayout()
        self._left_actions.setContentsMargins(0, 0, 0, 0)
        self._left_actions.setSpacing(2)
        top.addLayout(self._left_actions)

        top.addWidget(self._mode_toggle)
        top.addWidget(self._brand_label)
        top.addSpacing(20)
        top.addWidget(self._mode_stack, 1)
        top.addSpacing(20)
        top.addWidget(self._reset_alarm_btn)

        outer.addLayout(top)
        outer.addSpacing(6)

    def add_left_action_widget(self, widget: QWidget) -> None:
        """Добавить виджет в левую action-полосу (перед кнопкой-переключателем)."""
        self._left_actions.addWidget(widget)

    def _on_mode_changed(self, mode: int) -> None:
        self._mode_stack.setCurrentIndex(mode)
        set_view_mode(KEY_HEADER_MODE, mode)

    # Публичные хелперы для апдейта контента (для будущего)
    def set_ticker_text(self, text: str) -> None:
        self._info_ticker.set_text(text)

    def set_status(self, key: str, text: str, *, color: str | None = None) -> None:
        self._status_strip.set_status(key, text, color=color)

    def get_signal_map(self) -> dict[str, Any]:
        """Каталог сигналов (для совместимости с ISignalProvider)."""
        return {
            "action_triggered": self.action_triggered,
            "header_button_clicked": self._buttons_widget.button_clicked,
            "mode_changed": self._mode_toggle.mode_changed,
        }
