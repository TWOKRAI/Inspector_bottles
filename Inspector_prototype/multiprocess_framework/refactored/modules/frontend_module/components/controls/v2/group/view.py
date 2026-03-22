# -*- coding: utf-8 -*-
"""
GroupView — композиция Label + Value, реализует INumericView.

Группа объединяет LabelView и SliderValueView/SpinBoxValueView.
"""
from __future__ import annotations

from typing import Callable, Literal, Optional

from frontend_module.components.controls.v2.base.interfaces import INumericView
from frontend_module.components.controls.v2.label.view import LabelView
from frontend_module.components.controls.v2.slider.view import SliderValueView
from frontend_module.components.controls.v2.spinbox.view import SpinBoxValueView
from frontend_module.core.qt_imports import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

LAYOUT_SPACING_AFTER_LABEL_PX = 5
LAYOUT_SPACING_BEFORE_VALUE_PX = 10


def _create_labeled_numeric_view(
    view_type: Literal["slider", "spinbox"],
    value_config: Optional[object] = None,
    label_position: str = "left",
) -> "LabeledNumericGroupView":
    """Создать группу Label + Value (slider или spinbox)."""
    value_config = value_config or object()
    show_ticks = getattr(value_config, "show_ticks", False)
    tick_interval = getattr(value_config, "tick_interval", None) or 10

    if view_type == "slider":
        value_view = SliderValueView(
            show_ticks=bool(show_ticks), tick_interval=int(tick_interval)
        )
    elif view_type == "spinbox":
        value_view = SpinBoxValueView()
    else:
        raise ValueError(f"Unknown view_type: {view_type!r}")

    return LabeledNumericGroupView(
        label_view=LabelView(),
        value_view=value_view,
        label_position=label_position,
    )


class LabeledNumericGroupView(QWidget):
    """
    Группа: LabelView + SliderValueView или SpinBoxValueView.
    Реализует INumericView для совместимости с NumericPresenter.
    """

    def __init__(
        self,
        label_view: LabelView,
        value_view: "SliderValueView | SpinBoxValueView",
        label_position: str = "left",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._label_view = label_view
        self._value_view = value_view
        self._label_position = label_position
        self._build_layout()

    def _build_layout(self) -> None:
        if self._label_position in ("top", "bottom"):
            layout = QVBoxLayout(self)
            first, second = (
                (self._label_view, self._value_view)
                if self._label_position == "top"
                else (self._value_view, self._label_view)
            )
            layout.addWidget(first)
            layout.addSpacing(LAYOUT_SPACING_AFTER_LABEL_PX)
            layout.addWidget(second, 1)
        else:
            layout = QHBoxLayout(self)
            if self._label_position == "left":
                layout.addWidget(self._label_view)
                layout.addSpacing(LAYOUT_SPACING_AFTER_LABEL_PX)
                layout.addSpacing(LAYOUT_SPACING_BEFORE_VALUE_PX)
                layout.addWidget(self._value_view, 1)
            else:  # right
                layout.addWidget(self._value_view, 1)
                layout.addSpacing(LAYOUT_SPACING_AFTER_LABEL_PX)
                layout.addWidget(self._label_view)

    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        self._label_view.setup(text=label, tooltip=tooltip)
        self._value_view.set_enabled(enabled)

    def set_value(self, value: float) -> None:
        self._value_view.set_value_silent(value)

    def set_value_silent(self, value: float) -> None:
        self._value_view.set_value_silent(value)

    def get_value(self) -> float:
        return self._value_view.get_value()

    def set_enabled(self, enabled: bool) -> None:
        self._value_view.set_enabled(enabled)

    def set_range(self, min_val: float, max_val: float, step: float) -> None:
        self._value_view.set_range(min_val, max_val, step)

    def set_validator_int(self) -> None:
        self._value_view.set_validator_int()

    def set_validator_float(self) -> None:
        self._value_view.set_validator_float()

    def on_changed(self, callback: Callable[[float], None]) -> None:
        self._value_view.on_changed(callback)

    def on_finished(self, callback: Callable[[float], None]) -> None:
        self._value_view.on_finished(callback)

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Ошибка валидации", message)

    def get_legacy_element(self) -> object:
        return self._value_view.get_legacy_element()


def create_labeled_numeric_view(
    view_type: Literal["slider", "spinbox"],
    value_config: Optional[object] = None,
    label_position: str = "left",
) -> LabeledNumericGroupView:
    """Фабрика: создать Label+Value группу."""
    return _create_labeled_numeric_view(view_type, value_config, label_position)
