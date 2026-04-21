"""Команды и register-хендлеры для ProcessorProcess.

Фабричные функции получают зависимости как аргументы и возвращают dict.
"""
from __future__ import annotations


def build_command_table(service) -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command().

    Args:
        service: ProcessorService instance.
    """

    def cmd_set_color_range(data: dict) -> dict:
        return service.set_color_range(data.get("color_lower"), data.get("color_upper"))

    def cmd_set_min_area(data: dict) -> dict:
        value = service.set_min_area(
            data.get("min_area", service.detector.min_area)
        )
        return {"status": "ok", "min_area": value}

    def cmd_set_max_area(data: dict) -> dict:
        value = service.set_max_area(
            data.get("max_area", service.detector.max_area)
        )
        return {"status": "ok", "max_area": value}

    return {
        "set_color_range": cmd_set_color_range,
        "set_min_area": cmd_set_min_area,
        "set_max_area": cmd_set_max_area,
    }


def build_register_handlers(service) -> dict:
    """Возвращает {field_name: handler} для apply_register_update().

    Args:
        service: ProcessorService instance.
    """
    return {
        "color_lower": lambda v: service.set_color_range(lower=v),
        "color_upper": lambda v: service.set_color_range(upper=v),
        "min_area": lambda v: service.set_min_area(v),
        "max_area": lambda v: service.set_max_area(v),
    }
