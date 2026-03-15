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

    launcher.add_process("camera", {
        "class": "multiprocess_prototype.processes.camera_process.CameraProcess",
        "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 50}},
        "priority": "high",
        "workers": {},
        "config": {
            "fps": 10,
            "resolution_width": 320,
            "resolution_height": 240,
            "use_simulator": True,
        },
    })

    launcher.add_process("processor", {
        "class": "multiprocess_prototype.processes.processor_process.ProcessorProcess",
        "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 50}},
        "priority": "high",
        "workers": {},
        "config": {
            "min_area": 500,
            "color_lower": [0, 0, 150],
            "color_upper": [100, 100, 255],
        },
    })

    # Запуск в фоне, остановка через 4 сек
    launcher.start()
    time.sleep(4.0)
    launcher.stop()
    launcher.wait()

    print("Camera+Processor test: OK")


if __name__ == "__main__":
    test_camera_processor_together()
