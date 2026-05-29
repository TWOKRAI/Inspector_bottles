"""InterfaceSection — секция «Настройка интерфейса» во вкладке Settings.

Содержит кнопку «Обновить UI» — перезапускает Qt event loop,
полностью пересоздавая главное окно, все табы и тему оформления
без перезапуска самого процесса.

SectionProtocol:
    key         = "interface_settings"
    title       = "Настройка интерфейса"
    widget()    → self
    action_buttons() → []
    on_activated()   → None
    on_deactivated() → None
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_logger = logging.getLogger(__name__)


class InterfaceSection(QWidget):
    """Секция «Настройка интерфейса» — управление UI без перезапуска процесса.

    Реализует SectionProtocol: key, title, widget(), action_buttons(),
    on_activated(), on_deactivated().

    G.5.2: принимает узкий callback `request_ui_restart` (Interface Segregation —
    секция знает только «перезапусти UI», не GuiProcess). Если None —
    кнопка «Обновить UI» показывается, но не выполняет перезапуск (graceful degradation).
    """

    # SectionProtocol — идентификаторы секции
    key: str = "interface_settings"
    title: str = "Настройка интерфейса"

    def __init__(
        self,
        request_ui_restart: "Callable[[], None] | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._request_ui_restart = request_ui_restart
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # === Группа: Управление интерфейсом ===
        group = QGroupBox("Управление интерфейсом")
        group_layout = QVBoxLayout(group)

        desc = QLabel(
            "Пересоздание UI полностью перезапускает графический интерфейс: "
            "главное окно, все вкладки, тема оформления — "
            "без перезапуска приложения и без потери IPC-соединений."
        )
        desc.setWordWrap(True)
        desc.setObjectName("HintLabelLg")
        group_layout.addWidget(desc)

        # Кнопка «Обновить UI»
        btn_row = QHBoxLayout()
        self._btn_rebuild = QPushButton("Обновить UI")
        self._btn_rebuild.setToolTip("Перезапустить графический интерфейс (процесс продолжит работу)")
        self._btn_rebuild.setMinimumWidth(200)
        self._btn_rebuild.setMinimumHeight(36)
        self._btn_rebuild.setProperty("role", "primary")
        self._btn_rebuild.clicked.connect(self._on_rebuild_ui)
        btn_row.addWidget(self._btn_rebuild)
        btn_row.addStretch()
        group_layout.addLayout(btn_row)

        layout.addWidget(group)
        layout.addStretch()

    # ------------------------------------------------------------------
    # SectionProtocol
    # ------------------------------------------------------------------

    def widget(self) -> "InterfaceSection":
        """Вернуть виджет секции (self)."""
        return self

    def action_buttons(self) -> list:
        """Кнопки секции для action-колонки (пустой список)."""
        return []

    def on_activated(self) -> None:
        """Вызывается при переключении на эту секцию."""

    def on_deactivated(self) -> None:
        """Вызывается при уходе с этой секции."""

    # ------------------------------------------------------------------
    # Обработчики
    # ------------------------------------------------------------------

    def _on_rebuild_ui(self) -> None:
        """Перезапустить UI через injected callback.

        Если callback=None (тесты без runtime) — graceful no-op (G.5.2).
        """
        if self._request_ui_restart is None:
            _logger.warning("[InterfaceSection] request_ui_restart=None — перезапуск UI недоступен")
            return

        _logger.info("[InterfaceSection] Перезапуск UI по запросу пользователя")
        self._request_ui_restart()
