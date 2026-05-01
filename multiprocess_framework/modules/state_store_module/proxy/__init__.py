"""proxy — клиентская часть StateStore.

StateProxy        — клиентский прокси для любого ProcessModule.
GuiStateProxy     — Qt-safe вариант для GUI-процесса (lazy PySide6).
"""
from .state_proxy import StateProxy
from .gui_state_proxy import GuiStateProxy

__all__ = ["StateProxy", "GuiStateProxy"]
