"""Inspector Prototype v3 — entry point.

SystemLauncher facade, Dict at Boundary configs via process().
Usage: python Inspector_prototype/multiprocess_prototype_v3/main.py
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent  # Inspector_prototype
_modules = _root / "multiprocess_framework" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main() -> int:
    from multiprocess_framework.modules.process_manager_module import SystemLauncher
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_prototype_v3.app_config import (
        CameraConfig, ProcessorConfig, RendererConfig,
        RobotConfig, DatabaseConfig, GuiConfig,
    )
    from multiprocess_prototype_v3.persistence import get_camera_type

    launcher = SystemLauncher(stop_timeout=5.0)

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
