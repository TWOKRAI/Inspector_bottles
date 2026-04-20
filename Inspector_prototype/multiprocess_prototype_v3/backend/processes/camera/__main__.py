"""Standalone: python -m multiprocess_prototype_v3.services.camera"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent.parent  # Inspector_prototype
_modules = _root / "multiprocess_framework" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_framework.modules.data_schema_module import process
from multiprocess_framework.modules.process_manager_module import SystemLauncher
from multiprocess_prototype_v3.services.camera.config import CameraConfig

if __name__ == "__main__":
    launcher = SystemLauncher(stop_timeout=3.0)
    launcher.add_process(*process(CameraConfig()))
    launcher.run()
