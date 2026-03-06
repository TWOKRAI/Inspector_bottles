"""
Точка входа для многопроцессного приложения.

SystemLauncher — фасад: создание процессов и воркеров через конфиги.
"""

import sys
from pathlib import Path

_prototype_root = Path(__file__).resolve().parent.parent
if str(_prototype_root) not in sys.path:
    sys.path.insert(0, str(_prototype_root))


def main():
    from multiprocess_framework.refactored.modules.process_manager_module.launcher import SystemLauncher
    from multiprocess_prototype.processes.process_1 import Process1Config
    from multiprocess_prototype.processes.process_1.worker_1 import Worker1Config
    from multiprocess_prototype.processes.process_2 import Process2Config
    from multiprocess_prototype.processes.process_2.worker_2 import Worker2_1Config, Worker2_2Config

    launcher = SystemLauncher()

    process_1 = launcher.create_process(Process1Config())
    process_1.add_worker(Worker1Config())
    launcher.add_process(process_1)

    process_2 = launcher.create_process(Process2Config())
    process_2.add_worker(Worker2_1Config())
    process_2.add_worker(Worker2_2Config())
    launcher.add_process(process_2)

    launcher.run()
    launcher.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
