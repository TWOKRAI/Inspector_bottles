# multiprocess_prototype_v3/main.py
"""Точка входа v3: SystemLauncher + спецификация процессов из launch_specs."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_modules = _root / "multiprocess_framework" / "modules"
for _p in (_root, _modules):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)


def main() -> None:
    from multiprocess_framework.modules.process_manager_module import SystemLauncher

    from multiprocess_prototype_v3.backend.configs.launch_specs import build_default_launch_tuples

    launcher = SystemLauncher(stop_timeout=5.0)
    for name, proc_dict in build_default_launch_tuples():
        launcher.add_process(name, proc_dict)
    launcher.run()


if __name__ == "__main__":
    main()
