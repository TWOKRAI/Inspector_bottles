# -*- coding: utf-8 -*-
"""
LayoutComposer — сборка контейнера из списка дескрипторов виджетов.

Добавляет виджеты в layout родителя по порядку. Гибкий: orientation, spacing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from frontend_module.core.qt_imports import QHBoxLayout, QVBoxLayout


def compose_layout(
    parent: Any,
    descriptors: List[Dict[str, Any]],
    widget_registry: Any,
    registers_manager: Optional[Any] = None,
    *,
    orientation: str = "vertical",
    spacing: int = 8,
) -> List[Any]:
    """
    Собрать layout из дескрипторов виджетов.

    Args:
        parent: Родительский виджет (должен иметь setLayout или layout)
        descriptors: Список dict с widget_type, register_name, field_name, ...
        widget_registry: WidgetRegistry для создания виджетов
        registers_manager: RegistersManager для привязки
        orientation: "vertical" | "horizontal"
        spacing: Отступ между виджетами

    Returns:
        Список созданных виджетов
    """
    layout_cls = QVBoxLayout if orientation == "vertical" else QHBoxLayout
    layout = layout_cls(parent)
    layout.setSpacing(spacing)

    widgets: List[Any] = []
    for d in descriptors:
        wtype = d.get("widget_type", "slider")
        w = widget_registry.create(wtype, d, registers_manager, parent)
        if w is not None:
            layout.addWidget(w)
            widgets.append(w)

    if hasattr(parent, "setLayout"):
        parent.setLayout(layout)
    elif hasattr(parent, "layout") and parent.layout() is None:
        parent.setLayout(layout)

    return widgets
