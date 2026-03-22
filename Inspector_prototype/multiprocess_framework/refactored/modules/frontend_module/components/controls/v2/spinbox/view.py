# -*- coding: utf-8 -*-
"""
SpinBoxValueView — только QDoubleSpinBox, без подписи.
"""
from __future__ import annotations

from typing import Callable, Optional

from frontend_module.components.controls.v2.base.infrastructure.signal_utils import (
    block_signals,
)
from frontend_module.core.qt_imports import (
    QDoubleSpinBox,
    QHBoxLayout,
    QWidget,
    pyqtSignal,
)


class SpinBoxValueView(QWidget):
    """Value: QDoubleSpinBox. value_changed, value_finished при Enter."""

    value_changed = pyqtSignal(float)
    value_finished = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._spinbox = QDoubleSpinBox()
        QHBoxLayout(self).addWidget(self._spinbox)
        self._spinbox.valueChanged.connect(lambda v: self.value_changed.emit(float(v)))
        self._spinbox.editingFinished.connect(
            lambda: self.value_finished.emit(self._spinbox.value())
        )

    def set_range(self, min_val: float, max_val: float, step: float) -> None:
        self._spinbox.setMinimum(min_val)
        self._spinbox.setMaximum(max_val)
        self._spinbox.setSingleStep(step)

    def set_validator_int(self) -> None:
        self._spinbox.setDecimals(0)

    def set_validator_float(self) -> None:
        self._spinbox.setDecimals(4)

    def set_value_silent(self, value: float) -> None:
        with block_signals(self._spinbox):
            self._spinbox.setValue(value)

    def get_value(self) -> float:
        return self._spinbox.value()

    def set_enabled(self, enabled: bool) -> None:
        self._spinbox.setEnabled(enabled)

    def on_changed(self, callback: Callable[[float], None]) -> None:
        self.value_changed.connect(callback)

    def on_finished(self, callback: Callable[[float], None]) -> None:
        self.value_finished.connect(callback)

    def get_legacy_element(self) -> object:
        return self._spinbox
