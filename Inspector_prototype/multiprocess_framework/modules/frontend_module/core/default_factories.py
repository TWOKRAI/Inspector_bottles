# -*- coding: utf-8 -*-
"""
Фабрики виджетов по умолчанию для WidgetRegistry.

Регистрирует slider и checkbox. Расширяемо: добавить новый тип = новая функция + register().
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from frontend_module.components.base.touch_keyboard_config import coerce_touch_keyboard
from frontend_module.core.widget_registry import WidgetRegistry
from frontend_module.interfaces import IRegistersManager


def _slider_config_from_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Извлечь SliderConfig-поля из kwargs."""
    config: Dict[str, Any] = {}
    for key in (
        "register_name",
        "field_name",
        "access_level",
        "label",
        "transfer_k",
        "round_k",
        "ui_elements",
        "controls",
        "callback",
        "touch_keyboard",
        "touch_keyboard_factory",
    ):
        if key in kwargs and kwargs[key] is not None:
            config[key] = kwargs.pop(key, None)
    if "extra" in kwargs:
        extra = kwargs.pop("extra")
        if isinstance(extra, dict):
            for k in (
                "register_name",
                "field_name",
                "access_level",
                "label",
                "transfer_k",
                "round_k",
                "ui_elements",
                "controls",
                "callback",
                "touch_keyboard",
                "touch_keyboard_factory",
            ):
                if k in extra and k not in config:
                    config[k] = extra[k]
    return config if config else None


def _checkbox_config_from_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Извлечь CheckboxConfig-поля из kwargs."""
    config: Dict[str, Any] = {}
    for key in ("register_name", "field_name", "access_level", "label", "position"):
        if key in kwargs and kwargs[key] is not None:
            config[key] = kwargs.pop(key, None)
    if "extra" in kwargs:
        extra = kwargs.pop("extra")
        if isinstance(extra, dict):
            for k in ("register_name", "field_name", "access_level", "label", "position"):
                if k in extra and k not in config:
                    config[k] = extra[k]
    return config if config else None


def _create_slider(
    widget_type: str,
    kwargs: Dict[str, Any],
    registers_manager: Optional[IRegistersManager],
    parent: Optional[Any],
) -> Optional[Any]:
    """Фабрика NumericControl (slider)."""
    from frontend_module.components import (
        BindingConfig,
        NumericControl,
        NumericViewConfig,
    )

    kwargs = dict(kwargs)
    config = _slider_config_from_kwargs(kwargs)
    if not config or not config.get("register_name") or not config.get("field_name"):
        return None
    binding = BindingConfig(
        register_name=config["register_name"],
        field_name=config["field_name"],
    )
    view_config = NumericViewConfig(
        view_type="slider",
        label=config.get("label"),
        touch_keyboard=coerce_touch_keyboard(config.get("touch_keyboard")),
        touch_keyboard_factory=config.get("touch_keyboard_factory"),
    )
    result = NumericControl.create(registers_manager, binding, view_config)
    return result.widget


def _create_checkbox(
    widget_type: str,
    kwargs: Dict[str, Any],
    registers_manager: Optional[IRegistersManager],
    parent: Optional[Any],
) -> Optional[Any]:
    """Фабрика CheckboxControl."""
    from frontend_module.components import (
        BindingConfig,
        CheckboxControl,
        CheckboxViewConfig,
    )

    kwargs = dict(kwargs)
    config = _checkbox_config_from_kwargs(kwargs)
    if not config or not config.get("register_name") or not config.get("field_name"):
        return None
    binding = BindingConfig(
        register_name=config["register_name"],
        field_name=config["field_name"],
    )
    view_config = CheckboxViewConfig(
        position=config.get("position", "left"),
        label=config.get("label"),
    )
    result = CheckboxControl.create(registers_manager, binding, view_config)
    return result.widget


def create_default_registry() -> WidgetRegistry:
    """Создать WidgetRegistry с зарегистрированными slider и checkbox."""
    registry = WidgetRegistry()
    registry.register("slider", _create_slider)
    registry.register("checkbox", _create_checkbox)
    return registry
