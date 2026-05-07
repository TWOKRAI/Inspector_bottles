"""ColorTripletWidget — заглушка виджета выбора цвета (3 спинбокса RGB).

Полноценный ColorPicker с HSV-колесом — Phase 10B.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QSpinBox, QWidget


class ColorTripletWidget(QWidget):
    """Три QSpinBox в горизонтальном ряду для RGB-триплета (0..255).

    Сигнал ``value_changed`` эмитится при изменении любого из трёх каналов.
    """

    value_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._spins: list[QSpinBox] = []
        for _i in range(3):
            spin = QSpinBox(self)
            spin.setRange(0, 255)
            spin.setValue(0)
            spin.valueChanged.connect(self._on_any_changed)
            layout.addWidget(spin)
            self._spins.append(spin)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def get_value(self) -> tuple[int, int, int]:
        """Вернуть текущий RGB-триплет."""
        return (
            self._spins[0].value(),
            self._spins[1].value(),
            self._spins[2].value(),
        )

    def set_value(self, rgb: tuple[int, int, int]) -> None:
        """Установить RGB-триплет (блокирует сигналы на время установки)."""
        for spin, val in zip(self._spins, rgb, strict=True):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        # Эмитим один раз после установки всех трёх
        self.value_changed.emit()

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------

    def _on_any_changed(self) -> None:
        """Проксирует valueChanged от любого спинбокса."""
        self.value_changed.emit()
