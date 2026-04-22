# multiprocess_prototype/main.py
"""
Точка входа Inspector Prototype.

SystemLauncher — фасад process_manager_module.
add_process(name, proc_dict) — Dict at Boundary.
Конфиги с build() через process() из data_schema_module.

Запуск:
  Прямой запуск (рекомендуется):
    python Inspector_prototype/multiprocess_prototype/main.py
  Или через run-скрипты (задают PYTHONPATH):
    .\Inspector_prototype\multiprocess_prototype\run.ps1
    ./Inspector_prototype/multiprocess_prototype/run.sh
"""
import sys
from pathlib import Path

# Для прямого запуска main.py — настроить пути, если модули не в PYTHONPATH
_root = Path(__file__).resolve().parent.parent  # Inspector_prototype
_modules = _root / "multiprocess_framework" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main() -> int:
    from multiprocess_framework.modules.process_manager_module import (
        SystemLauncher,
    )
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_prototype.backend.configs import (
        CameraConfig,
        DatabaseConfig,
        GuiConfig,
        ProcessorConfig,
        RendererConfig,
        RobotConfig,
    )

    launcher = SystemLauncher(stop_timeout=5.0)

    from multiprocess_prototype.persistence import get_camera_type
    camera_type = get_camera_type()

    launcher.add_process(*process(CameraConfig(camera_type=camera_type)))
    launcher.add_process(*process(ProcessorConfig()))
    launcher.add_process(*process(RendererConfig()))
    launcher.add_process(*process(RobotConfig()))
    launcher.add_process(*process(DatabaseConfig()))
    launcher.add_process(*process(GuiConfig(camera_type=camera_type)))

    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
