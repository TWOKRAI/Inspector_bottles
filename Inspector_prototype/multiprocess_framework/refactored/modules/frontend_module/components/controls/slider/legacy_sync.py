# -*- coding: utf-8 -*-
"""
Legacy-синхронизация: обновление словарей ui_elements / controls для совместимости со старым UI.

Используется SliderControl при сборке UI. Не выполняет notify/send_register_update —
это делает common/field_sync.py после записи.
"""
from __future__ import annotations

from typing import Any, Optional


def publish_legacy_ui_refs(
    *,
    field_name: Optional[str],
    value: Any,
    slider_element: Optional[Any],
    can_modify: bool,
    ui_elements: Optional[dict],
    controls: Any,
    resolved_meta: Optional[Any],
) -> None:
    """
    Включить/выключить слайдер и обновить legacy-словари ui_elements / controls.

    Словари используются совместимостью со старым UI монолита.
    """
    if slider_element is not None:
        slider_element.setEnabled(can_modify)
    if ui_elements is not None and field_name:
        meta_raw = resolved_meta.raw if resolved_meta else {}
        ui_elements[field_name] = {
            "element": slider_element,
            "value": value,
            "min_access": meta_raw.get("access_level", 0),
            "transfer_k": resolved_meta.transfer_k if resolved_meta else 1.0,
            "round_k": resolved_meta.round_k if resolved_meta else 0,
        }
    if controls is not None and field_name:
        if isinstance(controls, list):
            for ctrl in controls:
                ctrl[field_name] = value
        else:
            controls[field_name] = value
