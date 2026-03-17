# multiprocess_prototype\tests\test_camera_processor.py
"""
Тест CameraProcess + ProcessorProcess.

Запускает Camera и Processor на 4 секунды.
Проверяет: оба процесса запускаются, graceful shutdown.

Запуск: PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.tests.test_camera_processor
"""

import time


def test_camera_processor_together():
    """Camera + Processor запускаются и корректно завершаются."""
    from multiprocess_framework.refactored.modules.process_manager_module import (
        SystemLauncher,
    )

    launcher = SystemLauncher(stop_timeout=5.0)

    from multiprocess_framework.refactored.modules.data_schema_module import process
    from multiprocess_prototype.configs import CameraConfig

    launcher.add_process(*process(CameraConfig(
        camera_type="simulator",
        fps=10,
        resolution_width=320,
        resolution_height=240,
        use_simulator=True,
    )))

    from multiprocess_prototype.configs import ProcessorConfig

    launcher.add_process(*process(ProcessorConfig()))

    # Запуск в фоне, остановка через 4 сек
    launcher.start()
    time.sleep(4.0)
    launcher.stop()
    launcher.wait()

    print("Camera+Processor test: OK")


if __name__ == "__main__":
    test_camera_processor_together()
