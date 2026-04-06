"""
Синхронизация register_update → состояние детектора.

Имена полей — как у плоского ``ProcessorRegisters`` (``registers/processor_registers.py``).

Поля ``crop_regions`` и ``post_processing_regions`` пока не разбираются здесь: снимок
для GUI/рецепта; применение к пайплайну — отдельная задача (см. ADR-092, прототип).
"""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_prototype_v2.registers.names import PROCESSOR_REGISTER


def apply_processor_register_update(
    data: dict,
    *,
    set_color_range: Callable[[dict], Any],
    set_min_area: Callable[[dict], Any],
    set_max_area: Callable[[dict], Any],
) -> None:
    if data.get("register_name") != PROCESSOR_REGISTER:
        return
    field = data.get("field_name")
    value = data.get("value")
    if field == "color_lower" and isinstance(value, (list, tuple)) and len(value) >= 3:
        set_color_range(
            {
                "color_lower": [int(value[i]) for i in range(3)],
                "color_upper": None,
            }
        )
    elif field == "color_upper" and isinstance(value, (list, tuple)) and len(value) >= 3:
        set_color_range(
            {
                "color_lower": None,
                "color_upper": [int(value[i]) for i in range(3)],
            }
        )
    elif field == "min_area":
        set_min_area({"min_area": value})
    elif field == "max_area":
        set_max_area({"max_area": value})
    # crop_regions / post_processing_regions: см. модульный docstring
