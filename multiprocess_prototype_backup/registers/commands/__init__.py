"""Commands domain: GUI command routing and payload catalog."""

from .catalog import GUI_COMMAND_CATALOG
from .routing import (
    COMMAND_TO_REGISTER_KEY,
    EXPLICIT_COMMAND_TARGETS,
    list_gui_command_ids,
    resolve_command_targets,
)

__all__ = [
    "GUI_COMMAND_CATALOG",
    "COMMAND_TO_REGISTER_KEY",
    "EXPLICIT_COMMAND_TARGETS",
    "list_gui_command_ids",
    "resolve_command_targets",
]
