# -*- coding: utf-8 -*-
"""
Сборка ``LabelView`` из UI-схемы (без ``RegistersManager``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from frontend_module.components._examples.label.schemas import (
    ExampleLabelUiConfig,
)
from frontend_module.components.label import LabelConfig, LabelView


@dataclass
class LabelExampleResult:
    """Корневой виджет — ``LabelView``."""

    widget: LabelView


def label_config_from_ui(ui: ExampleLabelUiConfig) -> LabelConfig:
    lt = ui.label_text.strip() or None
    tt = ui.tooltip_text.strip() or None
    return LabelConfig(
        label=lt,
        tooltip=tt,
        position=ui.label_position,
        visible=ui.label_visible,
    )


def coerce_ui(
    ui: Optional[Union[ExampleLabelUiConfig, dict]],
) -> ExampleLabelUiConfig:
    if ui is None:
        return ExampleLabelUiConfig()
    if isinstance(ui, ExampleLabelUiConfig):
        return ui
    return ExampleLabelUiConfig.model_validate(ui)


def create_example_label(
    ui: Optional[Union[ExampleLabelUiConfig, dict]] = None,
) -> LabelExampleResult:
    cfg = label_config_from_ui(coerce_ui(ui))
    view = LabelView()
    display = (cfg.label or "").strip() or "—"
    view.setup(text=display, tooltip=(cfg.tooltip or "").strip())
    view.setVisible(cfg.visible)
    return LabelExampleResult(widget=view)
