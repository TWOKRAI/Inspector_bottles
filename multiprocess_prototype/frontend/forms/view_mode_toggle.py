"""ViewMode enum + ViewModeToggle — переключатель между Cards и Table.

ViewModeToggle — switch-тумблер без текста. OFF = Cards, ON = Table.
При смене или программном set_mode() эмитит signal ``mode_changed``.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget


class ViewMode(StrEnum):
    """Режим отображения формы."""

    CARDS = "cards"
    TABLE = "table"


class ViewModeToggle(QWidget):
    """Переключатель Cards / Table — switch-тумблер без текста.

    OFF = Cards, ON = Table.

    Сигнал ``mode_changed`` эмитится:
    - при клике на тумблер;
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

        self._checkbox = QCheckBox(self)
        self._checkbox.setText("")
        self._checkbox.setToolTip("Cards / Table")
        self._checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checkbox.setObjectName("ViewModeSwitch")
        self._checkbox.setChecked(self._mode == ViewMode.TABLE)

        layout.addWidget(self._checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        self._checkbox.toggled.connect(self._on_toggled)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def mode(self) -> ViewMode:
        """Текущий режим отображения."""
        return self._mode

    def set_mode(self, mode: ViewMode) -> None:
        """Установить режим и эмитить mode_changed."""
        mode = ViewMode(mode)
        self._mode = mode
        self._checkbox.blockSignals(True)
        self._checkbox.setChecked(mode == ViewMode.TABLE)
        self._checkbox.blockSignals(False)
        self.mode_changed.emit(mode.value)

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------

    def _on_toggled(self, checked: bool) -> None:
        """Обработчик переключения тумблера."""
        self._mode = ViewMode.TABLE if checked else ViewMode.CARDS
        self.mode_changed.emit(self._mode.value)
