# multiprocess_prototype/frontend/__init__.py
"""
Frontend Inspector Prototype.

Организация:
- ``configs/`` — корень процесса: FrontendConfig, GuiConfigFrontend (реестр окон — в ``frontend_config``).
- ``windows/<feature>/`` — окно + свой config (main_window, loading, …).
- ``widgets/<feature>/`` — вкладка/виджет + config.py; общий слой вкладок — ``widgets/tabs/``.
- Универсальные Qt-компоненты — во ``frontend_module`` (фреймворк).

Регистры: ``multiprocess_prototype.registers.create_registers``.

``GuiProcessFrontend`` — алиас на ``GuiProcess`` (``backend.processes.gui.gui_process``).
"""

from multiprocess_prototype.backend.processes.gui.gui_process import GuiProcess as GuiProcessFrontend

from .configs import GuiConfigFrontend

__all__ = ["GuiConfigFrontend", "GuiProcessFrontend"]
