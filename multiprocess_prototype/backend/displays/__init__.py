"""Prototype-обёртка дисплеев: привязка DisplayRegistry к SystemBlueprint.

Публичный API:
    - ``bind_displays_to_blueprint``    — записать SHM-описания дисплеев в blueprint
    - ``cleanup_display_from_blueprint`` — удалить SHM-описание одного дисплея
"""

from .blueprint_binding import (
    bind_displays_to_blueprint,
    cleanup_display_from_blueprint,
)

__all__ = [
    "bind_displays_to_blueprint",
    "cleanup_display_from_blueprint",
]
