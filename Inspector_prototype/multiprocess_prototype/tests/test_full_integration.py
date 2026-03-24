# multiprocess_prototype\tests\test_full_integration.py
"""
Полный тест 5 процессов + graceful shutdown (Этап 8.3).

Запускает main.py через process() конфиги, ждёт 3 сек, останавливает через stop().
Требует DISPLAY для GUI (на headless CI — пропустить).
Запуск: PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.tests.test_full_integration
"""

import time

import pytest

from multiprocess_prototype.tests.support.gui_env import gui_display_available

# GUI: Windows / DISPLAY / QT_QPA_PLATFORM=offscreen
pytestmark = pytest.mark.skipif(
    not gui_display_available(),
    reason="GUI requires display or QT_QPA_PLATFORM=offscreen",
)


def test_full_5_processes_graceful_shutdown():
    """5 процессов (camera, processor, renderer, robot, gui) — запуск и graceful stop."""
    from multiprocess_framework.refactored.modules.process_manager_module import (
        SystemLauncher,
    )
    from multiprocess_framework.refactored.modules.data_schema_module import process
    from multiprocess_prototype.backend.configs import (
        CameraConfig,
        ProcessorConfig,
        RendererConfig,
        RobotConfig,
        GuiConfig,
    )

    launcher = SystemLauncher(stop_timeout=5.0)

    launcher.add_process(*process(CameraConfig()))
    launcher.add_process(*process(ProcessorConfig()))
    launcher.add_process(*process(RendererConfig()))
    launcher.add_process(*process(RobotConfig()))
    launcher.add_process(*process(GuiConfig()))

    launcher.start()
    time.sleep(3.0)
    launcher.stop()
    launcher.wait()

    status = launcher.get_status()
    assert status.get("spawner_running") is False or status.get("process", {}).get("is_alive") is False
    print("Full 5-process integration test: OK (graceful shutdown)")


if __name__ == "__main__":
    if not os.environ.get("DISPLAY"):
        print("Skipping: DISPLAY not set (GUI requires display)")
    else:
        test_full_5_processes_graceful_shutdown()
