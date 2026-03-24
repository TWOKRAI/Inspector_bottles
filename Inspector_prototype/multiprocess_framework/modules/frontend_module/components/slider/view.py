# -*- coding: utf-8 -*-
"""
SliderValueView — только QLineEdit + QSlider, без подписи.
"""
from __future__ import annotations

from typing import Callable, Optional

from frontend_module.components.base.infrastructure.signal_utils import (
    block_signals,
)
from frontend_module.components.common.slider_styles import (
    LAYOUT_SPACING_PX,
    SLIDER_MIN_HEIGHT_PX,
    apply_slider_handle_style,
)
from frontend_module.styling.context import get_style_session_from_parent
from frontend_module.core.qt_imports import (
    QDoubleValidator,
    QHBoxLayout,
    QIntValidator,
    QLineEdit,
    QSlider,
    QWidget,
    Qt,
    pyqtSignal,
)


class SliderValueView(QWidget):
    """Value: QLineEdit + QSlider. Сигналы value_changed, value_finished."""

    value_changed = pyqtSignal(float)
    value_finished = pyqtSignal(float)

    def __init__(
        self,
        show_ticks: bool = False,
        tick_interval: int = 10,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._line_edit = QLineEdit()
        self._line_edit.setAlignment(Qt.AlignCenter)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimumHeight(SLIDER_MIN_HEIGHT_PX)
        apply_slider_handle_style(
            self._slider, style_session=get_style_session_from_parent(self)
        )
        self._slider.wheelEvent = lambda e: None  # type: ignore[assignment]
        self._step = 1.0

        layout = QHBoxLayout(self)
        layout.addWidget(self._line_edit)
        layout.addSpacing(LAYOUT_SPACING_PX)
        layout.addWidget(self._slider, 1)

        if show_ticks:
            self._slider.setTickPosition(QSlider.TicksBelow)
            self._slider.setTickInterval(tick_interval)

        self._slider.valueChanged.connect(self._on_slider_moved)
        self._line_edit.editingFinished.connect(self._on_input_finished)

    def set_range(self, min_val: float, max_val: float, step: float) -> None:
        self._step = step
        self._slider.setMinimum(int(min_val / step))
        self._slider.setMaximum(int(max_val / step))

    def set_validator_int(self) -> None:
        self._line_edit.setValidator(QIntValidator())

    def set_validator_float(self) -> None:
        v = QDoubleValidator()
        if hasattr(v, "setNotation"):
            v.setNotation(QDoubleValidator.StandardNotation)
        self._line_edit.setValidator(v)

    def set_value_silent(self, value: float) -> None:
        slider_pos = int(value / self._step)
        decimals = self._get_decimals()
        fmt = f"{{0:.{decimals}f}}"
        with block_signals(self._slider, self._line_edit):
            self._slider.setValue(slider_pos)
            self._line_edit.setText(fmt.format(value))

    def get_value(self) -> float:
        try:
            return float(self._line_edit.text().replace(",", "."))
        except ValueError:
            return 0.0

    def set_enabled(self, enabled: bool) -> None:
        self._slider.setEnabled(enabled)
        self._line_edit.setEnabled(enabled)

    def on_changed(self, callback: Callable[[float], None]) -> None:
        self.value_changed.connect(callback)

    def on_finished(self, callback: Callable[[float], None]) -> None:
        self.value_finished.connect(callback)

    def get_legacy_element(self) -> object:
        return self._slider

    def _on_slider_moved(self, position: int) -> None:
        value = position * self._step
        decimals = self._get_decimals()
        self._line_edit.setText(f"{value:.{decimals}f}")
        self.value_changed.emit(value)

    def _on_input_finished(self) -> None:
        try:
            value = float(self._line_edit.text().replace(",", "."))
            self.value_finished.emit(value)
        except ValueError:
            self._on_slider_moved(self._slider.value())

    def _get_decimals(self) -> int:
        step_str = str(self._step)
        if "." in step_str:
            return len(step_str.split(".")[1].rstrip("0"))
        return 0
