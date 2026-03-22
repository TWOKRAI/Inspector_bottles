# -*- coding: utf-8 -*-
"""
Сборка QLayout для CheckboxControl: порядок метки и чекбокса по ``position``.

Виджет остаётся владельцем дочерних ``QWidget``; сюда передаются уже созданные
``QLabel`` и ``QCheckBox``.
"""
from __future__ import annotations

from typing import Any, Literal, Union

from frontend_module.components.controls.checkbox.styles import (
    LAYOUT_CONTENT_MARGINS_PX,
    LAYOUT_SPACING_PX,
)
from frontend_module.core.qt_imports import QHBoxLayout, QVBoxLayout

Position = Literal["left", "right", "top", "bottom"]


def create_checkbox_layout(
    position: Position,
    label_widget: Any,
    checkbox_widget: Any,
) -> Union[QHBoxLayout, QVBoxLayout]:
    """
    Создать ``QHBoxLayout`` или ``QVBoxLayout`` с меткой и чекбоксом в нужном порядке.

    Виджеты уже добавлены в layout; вызывающий делает ``parent.setLayout(layout)``.
    """
    if position in ("top", "bottom"):
        layout: Union[QHBoxLayout, QVBoxLayout] = QVBoxLayout()
        items: tuple[Any, ...] = (
            (label_widget, checkbox_widget)
            if position == "top"
            else (checkbox_widget, label_widget)
        )
    else:
        layout = QHBoxLayout()
        items = (
            (label_widget, checkbox_widget)
            if position == "left"
            else (checkbox_widget, label_widget)
        )

    layout.setContentsMargins(
        LAYOUT_CONTENT_MARGINS_PX,
        LAYOUT_CONTENT_MARGINS_PX,
        LAYOUT_CONTENT_MARGINS_PX,
        LAYOUT_CONTENT_MARGINS_PX,
    )
    layout.setSpacing(LAYOUT_SPACING_PX)
    for w in items:
        layout.addWidget(w)
    return layout
