# multiprocess_prototype\main.py
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
import os
import sys

# Windows: отключить MSMF HW transforms до загрузки OpenCV (обход grabFrame -1072875772)
# if os.name == "nt":
#     os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")
from pathlib import Path

# Пути: Inspector_prototype (содержит multiprocess_prototype, Services, multiprocess_framework)
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
        DatabaseConfig,
        ProcessorConfig,
        RendererConfig,
        RobotConfig,
        GuiConfig,
    )

    launcher = SystemLauncher(stop_timeout=5.0)

    # Тип камеры: из prefs (сохранён в GUI) → env INSPECTOR_CAMERA_TYPE → default
    from multiprocess_prototype.prefs import get_camera_type
    camera_type = get_camera_type()

    # Порядок: Camera создаёт shm первым, затем Processor, Renderer, Robot, Database, GUI
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
