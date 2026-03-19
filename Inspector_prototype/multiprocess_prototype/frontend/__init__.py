# multiprocess_prototype/frontend/__init__.py
"""
Frontend Inspector Prototype.

GUI-процесс, конфиг, окна.
Регистры: multiprocess_prototype.registers.create_registers
"""

from .configs import GuiConfigFrontend
from .process import GuiProcessFrontend
__all__ = [
    "GuiConfigFrontend",
    "GuiProcessFrontend",
]
