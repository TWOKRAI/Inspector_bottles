"""Inspector Prototype v3 — entry point."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent  # Inspector_prototype
_modules = _root / "multiprocess_framework" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main() -> int:
    from multiprocess_framework.modules.data_schema_module import process
    from multiprocess_framework.modules.process_manager_module import SystemLauncher

    from multiprocess_prototype_v3.config import AppConfig, CameraConfig
    from multiprocess_prototype_v3.persistence import get_camera_type

    camera_type = get_camera_type()
    app = AppConfig(
        camera=CameraConfig(camera_type=camera_type),
    )
    launcher = SystemLauncher(stop_timeout=app.stop_timeout)
    for cfg in app.all_process_configs():
        launcher.add_process(*process(cfg))
    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
