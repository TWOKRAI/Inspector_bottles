# -*- coding: utf-8 -*-
"""
Фабрика «подпись + числовое значение» (слайдер или спинбокс).

Вынесена из ``view.py``, чтобы ``LabeledNumericGroupView`` не импортировал ``spinbox``/``slider``
на уровне модуля — однонаправленный граф: примитивы → ``view`` → ``factory`` → примитивы.
"""
from __future__ import annotations

from typing import Literal, Optional

from frontend_module.components.group.view import LabeledNumericGroupView
from frontend_module.components.label.view import LabelView


def _create_labeled_numeric_view(
    view_type: Literal["slider", "spinbox"],
    value_config: Optional[object] = None,
    label_position: str = "left",
) -> LabeledNumericGroupView:
    value_config = value_config or object()
    show_ticks = getattr(value_config, "show_ticks", False)
    tick_interval = getattr(value_config, "tick_interval", None) or 10

    if view_type == "slider":
        from frontend_module.components.slider.view import SliderValueView

        value_view = SliderValueView(
            show_ticks=bool(show_ticks), tick_interval=int(tick_interval)
        )
    elif view_type == "spinbox":
        from frontend_module.components.spinbox.view import SpinBoxValueView

        value_view = SpinBoxValueView()
    else:
        raise ValueError(f"Unknown view_type: {view_type!r}")

    return LabeledNumericGroupView(
        label_view=LabelView(),
        value_view=value_view,
        label_position=label_position,
    )


def create_labeled_numeric_view(
    view_type: Literal["slider", "spinbox"],
    value_config: Optional[object] = None,
    label_position: str = "left",
) -> LabeledNumericGroupView:
    """Публичная фабрика: Label + Slider или Label + SpinBox."""
    return _create_labeled_numeric_view(view_type, value_config, label_position)
