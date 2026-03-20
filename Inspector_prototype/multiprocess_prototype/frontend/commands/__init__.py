# multiprocess_prototype/frontend/commands/__init__.py
"""GUI-команды."""

from multiprocess_prototype.registers.gui_command_catalog import GUI_COMMAND_CATALOG

from .gui_command_handler import GuiCommandHandler
from .message_manager_adapter import MessageManagerAdapter

__all__ = [
    "GuiCommandHandler",
    "GUI_COMMAND_CATALOG",
    "MessageManagerAdapter",
]
