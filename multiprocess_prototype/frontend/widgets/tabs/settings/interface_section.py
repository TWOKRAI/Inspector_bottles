"""InterfaceSection — секция «Настройка интерфейса» во вкладке Settings.

Содержит кнопку «Обновить UI» — перезапускает Qt event loop,
полностью пересоздавая главное окно, все табы и тему оформления
без перезапуска самого процесса.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
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
    """Секция «Настройка интерфейса» — управление UI без перезапуска процесса."""

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
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
        self._btn_rebuild.setToolTip(
            "Перезапустить графический интерфейс (процесс продолжит работу)"
        )
        self._btn_rebuild.setMinimumWidth(200)
        self._btn_rebuild.setMinimumHeight(36)
        self._btn_rebuild.setProperty("role", "primary")
        self._btn_rebuild.clicked.connect(self._on_rebuild_ui)
        btn_row.addWidget(self._btn_rebuild)
        btn_row.addStretch()
        group_layout.addLayout(btn_row)

        layout.addWidget(group)
        layout.addStretch()

    def _on_rebuild_ui(self) -> None:
        """Перезапустить UI: ставим флаг на процессе и закрываем QApplication."""
        process = self._ctx.process
        process._restart_ui = True
        _logger.info("[InterfaceSection] Перезапуск UI по запросу пользователя")

        app = QApplication.instance()
        if app is not None:
            app.quit()
