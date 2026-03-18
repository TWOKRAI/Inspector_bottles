# multiprocess_prototype/frontend/__init__.py
"""
Frontend Inspector Prototype.

GUI-процесс, конфиг, окна, регистры.
"""

from .config import GuiConfigFrontend
from .process import GuiProcessFrontend
from .registers import create_frontend_registers
from .windows import InspectorWindow

__all__ = [
    "GuiConfigFrontend",
    "GuiProcessFrontend",
    "create_frontend_registers",
    "InspectorWindow",
]
