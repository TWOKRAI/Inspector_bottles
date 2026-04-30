"""RegionForm — детальная форма редактирования одного региона."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class RegionForm(QWidget):
    """Детальная форма одного региона."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._block = False

        group = QGroupBox("Редактирование региона")
        g = QGridLayout(group)
        row = 0

        g.addWidget(QLabel("Имя:"), row, 0)
        self._name = QLineEdit()
        g.addWidget(self._name, row, 1, 1, 3)
        row += 1

        for lbl, attr, col_off in [
            ("x1:", "_x1", 0), ("y1:", "_y1", 2),
            ("x2:", "_x2", 0), ("y2:", "_y2", 2),
        ]:
            if col_off == 0:
                row += 1
            g.addWidget(QLabel(lbl), row, col_off)
            spin = QSpinBox()
            spin.setRange(0, 100000)
            setattr(self, attr, spin)
            g.addWidget(spin, row, col_off + 1)

        row += 1
        self._enabled = QCheckBox("Включён")
        self._is_main = QCheckBox("Основной (main)")
        self._processing = QCheckBox("Обработка включена")
        g.addWidget(self._enabled, row, 0, 1, 2)
        g.addWidget(self._is_main, row, 2, 1, 2)
        row += 1
        g.addWidget(self._processing, row, 0, 1, 2)

        row += 1
        g.addWidget(QLabel("Дисплей:"), row, 0)
        self._display = QLineEdit()
        self._display.setPlaceholderText("Имя дисплея (напр. display_0)")
        g.addWidget(self._display, row, 1, 1, 3)

        row += 1
        g.addWidget(QLabel("Комментарий:"), row, 0)
        self._comment = QLineEdit()
        g.addWidget(self._comment, row, 1, 1, 3)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.addStretch()

        self._name.editingFinished.connect(self._emit)
        self._display.editingFinished.connect(self._emit)
        self._comment.editingFinished.connect(self._emit)
        for sp in (self._x1, self._y1, self._x2, self._y2):
            sp.valueChanged.connect(self._emit)
        for cb in (self._enabled, self._is_main, self._processing):
            cb.stateChanged.connect(self._emit)

    def load(self, data: dict[str, Any]) -> None:
        self._block = True
        self._name.setText(str(data.get("name", "")))
        self._x1.setValue(int(data.get("x1", 0)))
        self._y1.setValue(int(data.get("y1", 0)))
        self._x2.setValue(int(data.get("x2", 0)))
        self._y2.setValue(int(data.get("y2", 0)))
        self._enabled.setChecked(bool(data.get("enabled", True)))
        self._is_main.setChecked(bool(data.get("is_main", False)))
        self._processing.setChecked(bool(data.get("processing_enabled", True)))
        self._display.setText(str(data.get("display", "")))
        self._comment.setText(str(data.get("comment", "")))
        self._block = False

    def read(self) -> dict[str, Any]:
        return {
            "name": self._name.text().strip(),
            "x1": self._x1.value(), "y1": self._y1.value(),
            "x2": self._x2.value(), "y2": self._y2.value(),
            "enabled": self._enabled.isChecked(),
            "is_main": self._is_main.isChecked(),
            "processing_enabled": self._processing.isChecked(),
            "display": self._display.text().strip(),
            "comment": self._comment.text().strip(),
        }

    def _emit(self) -> None:
        if not self._block:
            self.changed.emit()


__all__ = ["RegionForm"]
