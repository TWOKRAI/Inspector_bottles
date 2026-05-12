"""Селектор слотов — ряд пронумерованных кнопок с состояниями.

Виджет не знает об AppContext — принимает чистые данные,
не импортирует ничего из multiprocess_prototype.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


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
            btn.setObjectName("SlotButton")
            btn.setProperty("slotState", "empty")

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
        btn = self._buttons[index]
        btn.setProperty("slotState", state)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

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
