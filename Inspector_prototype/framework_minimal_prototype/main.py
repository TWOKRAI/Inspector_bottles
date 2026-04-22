# framework_minimal_prototype/main.py
"""
Точка входа минимального прототипа (один процесс-счётчик).

Запуск из корня репозитория:
  python Inspector_prototype/framework_minimal_prototype/main.py
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_modules = _root / "multiprocess_framework" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main() -> int:
    from multiprocess_framework.modules.process_manager_module import SystemLauncher
    from multiprocess_framework.modules.data_schema_module import process

    from framework_minimal_prototype.backend.configs.counter_config import CounterConfig

    launcher = SystemLauncher(stop_timeout=5.0)
    launcher.add_process(*process(CounterConfig()))
    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
