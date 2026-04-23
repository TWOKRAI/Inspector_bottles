"""Команды и register-хендлеры для RendererProcess.

Все команды — flag-setter'ы, генерируемые из SERVICE_FLAGS.
"""
from __future__ import annotations

# Флаги сервиса, управляемые через команды и register_update
SERVICE_FLAGS: tuple[str, ...] = (
    "show_original",
    "show_mask",
    "draw_contours",
    "draw_bboxes",
    "save_frames",
)


def build_command_table(service) -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command().

    Args:
        service: RendererService instance.
    """
    def make_setter(flag: str):
        def handler(data: dict) -> dict:
            setattr(service, flag, data.get(flag, getattr(service, flag)))
            return {"status": "ok"}
        return handler

    return {f"set_{flag}": make_setter(flag) for flag in SERVICE_FLAGS}


def build_register_handlers(service) -> dict:
    """Возвращает {field_name: handler} для apply_register_update().

    Args:
        service: RendererService instance.
    """
    def make(flag: str):
        return lambda v: setattr(service, flag, v)

    return {flag: make(flag) for flag in SERVICE_FLAGS}


def build_state_config_handlers(service) -> dict:
    """Маппинг config field suffix → handler для StateProxy callback.

    Args:
        service: RendererService instance.

    Returns:
        {flag: handler} для каждого флага из SERVICE_FLAGS.
        handler(value) вызывает setattr(service, flag, value).
    """
    def make(flag: str):
        return lambda v: setattr(service, flag, v)

    return {flag: make(flag) for flag in SERVICE_FLAGS}
