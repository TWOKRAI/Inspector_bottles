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
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

_logger = logging.getLogger(__name__)


class InterfaceSection(QWidget):
    """Секция «Настройка интерфейса» — управление UI без перезапуска процесса.

    Реализует SectionProtocol: key, title, widget(), action_buttons(),
    on_activated(), on_deactivated().

    Task D.5: принимает ctx как Optional для backward compat. Если ctx=None —
    кнопка «Обновить UI» показывается, но не выполняет перезапуск (graceful degradation).
    TODO Phase G (G.5): передавать ProcessControl Protocol через AppServices/RuntimeDeps.
    """

    # SectionProtocol — идентификаторы секции
    key: str = "interface_settings"
    title: str = "Настройка интерфейса"

    def __init__(
        self,
        ctx: "AppContext | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
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
        """Перезапустить UI: ставим флаг на процессе и закрываем QApplication.

        Если ctx=None (Task D.5 / тесты без полного AppContext) — graceful no-op.
        TODO Phase G (G.5): ProcessControl Protocol в AppServices устранит этот guard.
        """
        if self._ctx is None:
            _logger.warning("[InterfaceSection] ctx=None — перезапуск UI недоступен")
            return

        process = self._ctx.process
        process._restart_ui = True
        _logger.info("[InterfaceSection] Перезапуск UI по запросу пользователя")

        app = QApplication.instance()
        if app is not None:
            app.quit()
