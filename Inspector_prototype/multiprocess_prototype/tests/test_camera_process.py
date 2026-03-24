# multiprocess_prototype\tests\test_camera_process.py
"""
Тест CameraProcess в изоляции.

Запускает только CameraProcess на 3 секунды.
Использует process(CameraConfig()) — полный config с managers, memory.
Запуск: PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/modules" python -m multiprocess_prototype.tests.test_camera_process
"""

import time

from multiprocess_framework.modules.data_schema_module import process
from multiprocess_prototype.backend.configs import CameraConfig


def test_camera_process_isolated():
    """CameraProcess запускается и корректно завершается."""
    from multiprocess_framework.modules.process_manager_module import (
        SystemLauncher,
    )

    launcher = SystemLauncher(stop_timeout=5.0)

    launcher.add_process(*process(CameraConfig(
        fps=10,
        resolution_width=320,
        resolution_height=240,
        use_simulator=True,
    )))

    launcher.start()
    time.sleep(3.0)
    launcher.stop()
    launcher.wait()

    print("CameraProcess test: OK")


if __name__ == "__main__":
    test_camera_process_isolated()
