# multiprocess_prototype_v3/frontend/commands/__init__.py
"""GUI-команды."""

from multiprocess_prototype_v3.registers.commands.catalog import GUI_COMMAND_CATALOG

from .gui_command_handler import GuiCommandHandler

__all__ = [
    "GuiCommandHandler",
    "GUI_COMMAND_CATALOG",
]
