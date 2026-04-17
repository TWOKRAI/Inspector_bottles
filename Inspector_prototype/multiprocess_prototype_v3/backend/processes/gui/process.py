# multiprocess_prototype_v3/backend/processes/gui/process.py
"""Отдельный процесс с PyQt: слайдер FPS → register_update на camera_sim."""

from __future__ import annotations

from multiprocess_framework.modules.process_module import ProcessModule


class GuiProcess(ProcessModule):
    """Минимальный GUI без полного FrontendLauncher (v3 smoke / демо)."""

    def _init_application_threads(self) -> None:
        return

    def _init_system_threads(self) -> None:
        # GUI: QApplication drives the event loop; commands/UI use the app thread, not
        # ProcessModule default system workers (same pattern as v2 robot_simulator).
        pass

    def _stop_system_threads(self) -> None:
        pass

    def run(self) -> None:
        from multiprocess_prototype_v3.frontend.launcher import run_v3_gui

        run_v3_gui(self)
