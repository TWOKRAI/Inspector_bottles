"""
Точка входа Inspector Prototype.

SystemLauncher — фасад process_manager_module.
add_process(name, proc_dict) — Dict at Boundary.
Конфиги с build() через process() из data_schema_module.

Запуск:
  run.sh (рекомендуется):
    ./Inspector_prototype/multiprocess_prototype/run.sh
  или из каталога Inspector_prototype:
    ./multiprocess_prototype/run.sh

  python main.py (из каталога Inspector_prototype или multiprocess_prototype):
    python Inspector_prototype/multiprocess_prototype/main.py
    cd Inspector_prototype && python multiprocess_prototype/main.py

  через модуль с PYTHONPATH:
    PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/refactored/modules" python -m multiprocess_prototype.main
"""

import sys
from pathlib import Path

# Чтобы можно было запускать как python main.py (без run.sh)
_root = Path(__file__).resolve().parent.parent
_modules = _root / "multiprocess_framework" / "refactored" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


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
