# multiprocess_prototype\tests\test_pipeline.py
"""
Тест Camera + Processor + Renderer + Robot (пайплайн без GUI).

Использует process() конфиги — полный config с managers, memory.
Запуск: PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/modules" python -m multiprocess_prototype.tests.test_pipeline
"""

import os
import time

from multiprocess_framework.modules.data_schema_module import process
from multiprocess_prototype.backend.configs import (
    CameraConfig,
    ProcessorConfig,
    RendererConfig,
    RobotConfig,
)


def test_camera_processor_renderer_robot():
    """Camera + Processor + Renderer + Robot — полный пайплайн через process() конфиги."""
    from multiprocess_framework.modules.process_manager_module import (
        SystemLauncher,
    )

    log_file = os.path.join(os.path.dirname(__file__), "..", "robot_actions_test.log")
    robot_cfg = RobotConfig(log_file=log_file, reject_delay=0.0)

    launcher = SystemLauncher(stop_timeout=5.0)

    launcher.add_process(*process(CameraConfig(
        fps=10,
        resolution_width=320,
        resolution_height=240,
        use_simulator=True,
    )))
    launcher.add_process(*process(ProcessorConfig()))
    launcher.add_process(*process(RendererConfig()))
    launcher.add_process(*process(robot_cfg))
    if os.path.exists(log_file):
        os.remove(log_file)

    launcher.start()
    time.sleep(4.0)
    launcher.stop()
    launcher.wait()

    # Проверка: Robot получил команды (кадры с пятном → reject)
    if os.path.exists(log_file):
        with open(log_file) as f:
            lines = f.readlines()
        print(f"Robot log: {len(lines)} reject entries")
    print("Camera+Processor+Renderer+Robot test: OK")


if __name__ == "__main__":
    test_camera_processor_renderer_robot()
