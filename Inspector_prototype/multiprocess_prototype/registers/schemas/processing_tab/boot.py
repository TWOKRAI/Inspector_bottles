# -*- coding: utf-8 -*-
"""
Значения по умолчанию для boot-конфигов процессов = те же, что у регистров GUI.

Менять параметры синхронизации (цвет, площади, флаги отображения) — в
`ProcessorRegisters` / `RendererRegisters`; отсюда только читают бэкенд-конфиги.
"""

from __future__ import annotations

from typing import Any

from .processor import ProcessorRegisters
from .renderer import RendererRegisters


def processor_process_boot_values() -> dict[str, Any]:
    """Поля процессора, совпадающие с `ProcessorRegisters`."""
    r = ProcessorRegisters()
    return {
        "min_area": r.min_area,
        "max_area": r.max_area,
        "color_lower": list(r.color_lower),
        "color_upper": list(r.color_upper),
    }


def renderer_process_boot_values() -> dict[str, Any]:
    """Поля рендерера, совпадающие с `RendererRegisters`."""
    r = RendererRegisters()
    return {
        "show_original": r.show_original,
        "show_mask": r.show_mask,
        "draw_contours": r.draw_contours,
    }


def processor_max_area_clamp() -> int:
    """Верхняя граница max_area (не 0); для clamp в детекторе и валидации."""
    m = ProcessorRegisters.get_field_meta("max_area")
    if m is None or m.max is None:
        return 50000
    return int(m.max)
