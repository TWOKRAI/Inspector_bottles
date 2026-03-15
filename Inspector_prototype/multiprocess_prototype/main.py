"""
Точка входа Inspector Prototype.

SystemLauncher — фасад process_manager_module.
add_process(name, proc_dict) — Dict at Boundary.
Конфиги с build() через process() из data_schema_module.

Запуск (из Inspector_prototype или Inspector_bottles):
  ./Inspector_prototype/multiprocess_prototype/run.sh

Или с PYTHONPATH:
  PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.main
"""

import sys


def main() -> int:
    from multiprocess_framework.refactored.modules.process_manager_module import (
        SystemLauncher,
    )
    from multiprocess_framework.refactored.modules.data_schema_module import process
    from multiprocess_prototype.configs import (
        CameraConfig,
        ProcessorConfig,
        RendererConfig,
        RobotConfig,
        GuiConfig,
    )

    launcher = SystemLauncher(stop_timeout=5.0)

    # Порядок: Camera создаёт shm первым, затем Processor, Renderer, Robot, GUI
    launcher.add_process(*process(CameraConfig()))
    launcher.add_process(*process(ProcessorConfig()))
    launcher.add_process(*process(RendererConfig()))
    launcher.add_process(*process(RobotConfig()))
    launcher.add_process(*process(GuiConfig()))

    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
