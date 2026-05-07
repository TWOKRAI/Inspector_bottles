"""ViewMode enum + ViewModeToggle — переключатель между Cards и Table.

ViewModeToggle — два QPushButton в QHBoxLayout. При клике или программном
set_mode() эмитит signal ``mode_changed``.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ViewMode(StrEnum):
    """Режим отображения формы."""

    CARDS = "cards"
    TABLE = "table"


class ViewModeToggle(QWidget):
    """Маленький переключатель Cards / Table.

    Сигнал ``mode_changed`` эмитится:
    - при клике на кнопку;
    - при программном вызове ``set_mode()``.
    """

    mode_changed = Signal(str)  # ViewMode — StrEnum, передаём как str

    def __init__(
        self,
        initial_mode: ViewMode = ViewMode.CARDS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._mode = initial_mode

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()

        self._btn_cards = QPushButton("Cards", self)
        self._btn_table = QPushButton("Table", self)

        self._btn_cards.setCheckable(True)
        self._btn_table.setCheckable(True)

        layout.addWidget(self._btn_cards)
        layout.addWidget(self._btn_table)

        self._btn_cards.clicked.connect(lambda: self.set_mode(ViewMode.CARDS))
        self._btn_table.clicked.connect(lambda: self.set_mode(ViewMode.TABLE))

        # Установить начальное состояние (без эмита)
        self._update_buttons()

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def mode(self) -> ViewMode:
        """Текущий режим отображения."""
        return self._mode

    def set_mode(self, mode: ViewMode) -> None:
        """Установить режим и эмитить mode_changed."""
        mode = ViewMode(mode)  # нормализация str → ViewMode
        self._mode = mode
        self._update_buttons()
        self.mode_changed.emit(mode.value)

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------

    def _update_buttons(self) -> None:
        """Обновить checked-состояние кнопок."""
        self._btn_cards.setChecked(self._mode == ViewMode.CARDS)
        self._btn_table.setChecked(self._mode == ViewMode.TABLE)
