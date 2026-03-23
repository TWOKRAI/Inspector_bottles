# -*- coding: utf-8 -*-
"""
Демо ``group.create_labeled_numeric_view``: только виджет, без привязки к регистру.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from frontend_module.components.control_v2.examples.group.schemas import (
    ExampleGroupRowUiConfig,
)
from frontend_module.components.control_v2.group import create_labeled_numeric_view
from frontend_module.components.control_v2.group.view import LabeledNumericGroupView
from frontend_module.components.control_v2.numeric.config import NumericViewConfig


@dataclass
class GroupRowExampleResult:
    """Корневая группа Label + числовой виджет."""

    widget: LabeledNumericGroupView


def coerce_ui(
    ui: Optional[Union[ExampleGroupRowUiConfig, dict]],
) -> ExampleGroupRowUiConfig:
    if ui is None:
        return ExampleGroupRowUiConfig()
    if isinstance(ui, ExampleGroupRowUiConfig):
        return ui
    return ExampleGroupRowUiConfig.model_validate(ui)


def create_example_group_row(
    ui: Optional[Union[ExampleGroupRowUiConfig, dict]] = None,
) -> GroupRowExampleResult:
    u = coerce_ui(ui)
    value_cfg = NumericViewConfig(
        view_type=u.view_type,
        show_ticks=u.show_ticks,
        enabled=u.widget_enabled,
    )
    w = create_labeled_numeric_view(
        view_type=u.view_type,
        value_config=value_cfg,
        label_position=u.label_position,
    )
    label = u.row_label.strip()
    tooltip = u.row_tooltip.strip()
    w.setup(label=label, tooltip=tooltip, enabled=u.widget_enabled)
    lo, hi = u.value_min, u.value_max
    if lo is not None and hi is not None:
        w.set_range(float(lo), float(hi), float(u.step))
    w.set_value_silent(float(u.initial_value))
    return GroupRowExampleResult(widget=w)
