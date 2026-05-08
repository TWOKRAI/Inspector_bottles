"""Селектор слотов — ряд пронумерованных кнопок с состояниями.

Виджет не знает об AppContext — принимает чистые данные,
не импортирует ничего из multiprocess_prototype_2.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


# Стили кнопок по состоянию
_STYLES: dict[str, str] = {
    "empty": (
        "background: #3a3a3a; color: #888; border: 1px solid #555;"
    ),
    "occupied": (
        "background: #2d5a2d; color: #ccc; border: 1px solid #4caf50;"
    ),
    "selected": (
        "background: #1a5276; color: #fff; border: 2px solid #2196f3;"
    ),
}


class SlotSelector(QWidget):
    """Селектор слотов — ряд пронумерованных кнопок.

    Каждый слот может быть: empty, occupied, selected.
    """

    # Сигнал: индекс нажатого слота
    slot_selected = Signal(int)

    def __init__(self, count: int = 8, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._count = count
        self._states: list[str] = ["empty"] * count
        self._buttons: list[QPushButton] = []
        self._selected: int = -1

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        for i in range(count):
            btn = QPushButton(str(i))
            btn.setMinimumSize(40, 30)
            btn.setStyleSheet(_STYLES["empty"])

            # Захватить индекс через default-аргумент
            btn.clicked.connect(lambda _checked=False, idx=i: self._on_click(idx))

            self._buttons.append(btn)
            layout.addWidget(btn)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_slot_state(self, index: int, state: str) -> None:
        """Установить состояние слота и обновить стиль кнопки.

        Args:
            index: индекс слота (0-based).
            state: "empty" | "occupied" | "selected".
        """
        if index < 0 or index >= self._count:
            return
        self._states[index] = state
        style = _STYLES.get(state, _STYLES["empty"])
        self._buttons[index].setStyleSheet(style)

    def select(self, index: int) -> None:
        """Выделить слот: снять выделение с предыдущего, установить на новый.

        Args:
            index: индекс слота для выделения.
        """
        if index < 0 or index >= self._count:
            return

        # Снять выделение с предыдущего выбранного
        if self._selected >= 0 and self._selected != index:
            prev_state = self._states[self._selected]
            # Если предыдущий был "selected" — вернуть в "empty"
            if prev_state == "selected":
                self.set_slot_state(self._selected, "empty")

        self._selected = index
        self.set_slot_state(index, "selected")

    def selected_index(self) -> int:
        """Вернуть индекс выбранного слота или -1."""
        return self._selected

    def set_slot_label(self, index: int, text: str) -> None:
        """Установить текст кнопки слота.

        Args:
            index: индекс слота.
            text:  новый текст кнопки.
        """
        if index < 0 or index >= self._count:
            return
        self._buttons[index].setText(text)

    def count(self) -> int:
        """Вернуть количество слотов."""
        return self._count

    # ------------------------------------------------------------------
    # Внутренняя логика
    # ------------------------------------------------------------------

    def _on_click(self, index: int) -> None:
        """Обработчик нажатия на кнопку слота."""
        self.select(index)
        self.slot_selected.emit(index)
