# -*- coding: utf-8 -*-
"""
Синхронизация значения control с окружением после записи в регистр.

Общая логика: notify_field_changed, send_register_update родителя.
Опционально (legacy): ui_elements, controls, callback — для совместимости со старым UI.
"""
from __future__ import annotations

from typing import Any, Optional


def publish_control_value_to_observers(
    *,
    registers_manager: Any,
    register_name: Optional[str],
    field_name: Optional[str],
    value: Any,
    parent_widget: Optional[Any] = None,
    ui_elements: Optional[dict] = None,
    controls: Any = None,
    callback: Any = None,
) -> None:
    """
    Распространить значение после успешной записи: notify_field_changed,
    send_register_update родителя, опционально legacy ui_elements/controls/callback.

    Не выполняет set_field_value — только побочные эффекты после записи.
    """
    if hasattr(registers_manager, "notify_field_changed"):
        registers_manager.notify_field_changed(register_name, field_name, value)

    if ui_elements is not None and field_name and field_name in ui_elements:
        ui_elements[field_name]["value"] = value

    if controls is not None and field_name:
        if isinstance(controls, list):
            for ctrl in controls:
                ctrl[field_name] = value
        else:
            controls[field_name] = value

    if parent_widget and getattr(parent_widget, "send_register_update", None):
        parent_widget.send_register_update(register_name, field_name, value)
    elif callback is not None:
        if isinstance(callback, list):
            for fn in callback:
                fn()
        else:
            callback()
