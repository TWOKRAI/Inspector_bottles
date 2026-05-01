"""BaseEditorToolbar — переиспользуемый toolbar для editor-вкладок.

Поддерживает произвольный набор кнопок слева и опциональную кнопку
«Применить» справа с визуальной dirty-индикацией.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)

# Стиль кнопки Apply в «грязном» состоянии (несохранённые изменения)
_DIRTY_STYLE = (
    "QPushButton { background-color: #e8a838; color: white; font-weight: bold; }"
)


class BaseEditorToolbar(QWidget):
    """Горизонтальный toolbar для editor-вкладок.

    Аргументы конструктора:
        buttons     -- список кортежей (label, tooltip, callback).
                       Каждая кнопка создаётся как QPushButton слева от разделителя.
        show_apply  -- показывать кнопку «Применить» справа (по умолчанию True).
        parent      -- родительский виджет.

    Сигналы:
        apply_clicked -- эмитируется при нажатии кнопки «Применить».
    """

    apply_clicked = Signal()

    def __init__(
        self,
        buttons: list[tuple[str, str, Callable]] | None = None,
        *,
        show_apply: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # Хранилище кнопок по label
        self._buttons: dict[str, QPushButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Добавить кастомные кнопки слева
        for label, tooltip, callback in (buttons or []):
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            layout.addWidget(btn)
            self._buttons[label] = btn

        # Растяжимый разделитель между левыми кнопками и Apply
        spacer = QSpacerItem(
            0, 0,
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        layout.addItem(spacer)

        # Кнопка «Применить» справа
        self._apply_btn: QPushButton | None = None
        if show_apply:
            self._apply_btn = QPushButton("Применить")
            self._apply_btn.setToolTip("Сохранить изменения")
            self._apply_btn.setEnabled(False)
            self._apply_btn.clicked.connect(self.apply_clicked.emit)
            layout.addWidget(self._apply_btn)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_dirty(self, dirty: bool) -> None:
        """Обновить состояние кнопки Apply в зависимости от наличия изменений.

        dirty=True  -- включить кнопку, поставить оранжевый акцент.
        dirty=False -- выключить кнопку, убрать акцент.
        """
        if self._apply_btn is None:
            return
        self._apply_btn.setEnabled(dirty)
        self._apply_btn.setStyleSheet(_DIRTY_STYLE if dirty else "")

    def get_button(self, label: str) -> QPushButton | None:
        """Вернуть кнопку по её label, или None если не найдена."""
        return self._buttons.get(label)

    def set_button_enabled(self, label: str, enabled: bool) -> None:
        """Включить или выключить кнопку по label."""
        btn = self._buttons.get(label)
        if btn is not None:
            btn.setEnabled(enabled)
