# -*- coding: utf-8 -*-
"""
Фабрики виджетов по умолчанию для WidgetRegistry.

Регистрирует slider и checkbox. Расширяемо: добавить новый тип = новая функция + register().
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from frontend_module.core.widget_registry import WidgetRegistry
from frontend_module.interfaces import IRegistersManager


def _create_slider(
    widget_type: str,
    kwargs: Dict[str, Any],
    registers_manager: Optional[IRegistersManager],
    parent: Optional[Any],
) -> Optional[Any]:
    """Фабрика SliderControl."""
    from frontend_module.components.controls import SliderControl

    return SliderControl(
        registers_manager=registers_manager,
        parent=parent,
        **kwargs,
    )


def _create_checkbox(
    widget_type: str,
    kwargs: Dict[str, Any],
    registers_manager: Optional[IRegistersManager],
    parent: Optional[Any],
) -> Optional[Any]:
    """Фабрика CheckboxControl."""
    from frontend_module.components.controls import CheckboxControl

    return CheckboxControl(
        registers_manager=registers_manager,
        parent=parent,
        **kwargs,
    )


def create_default_registry() -> WidgetRegistry:
    """Создать WidgetRegistry с зарегистрированными slider и checkbox."""
    registry = WidgetRegistry()
    registry.register("slider", _create_slider)
    registry.register("checkbox", _create_checkbox)
    return registry
