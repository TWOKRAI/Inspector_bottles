# multiprocess_prototype/frontend/commands/__init__.py
"""GUI-команды."""

from .gui_command_handler import GuiCommandHandler, GUI_COMMAND_CATALOG
from .message_manager_adapter import MessageManagerAdapter

__all__ = [
    "GuiCommandHandler",
    "GUI_COMMAND_CATALOG",
    "MessageManagerAdapter",
]
