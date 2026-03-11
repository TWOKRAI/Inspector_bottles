"""
Точка входа для многопроцессного приложения.

SystemLauncher — фасад: add_process(name, proc_dict).
Конвертация config → dict через build_process_with_workers (Dict at Boundary).
"""

import sys


def main() -> int:
    from multiprocess_framework.refactored.modules.process_manager_module import (
        SystemLauncher,
    )
    from multiprocess_framework.refactored.modules.data_schema_module import process
    from multiprocess_prototype.processes.process_1 import Process1Config
    from multiprocess_prototype.processes.process_1.worker_1 import Worker1Config
    from multiprocess_prototype.processes.process_2 import Process2Config
    from multiprocess_prototype.processes.process_2.worker_2 import (
        Worker2_1Config,
        Worker2_2Config,
    )

    launcher = SystemLauncher()

    launcher.add_process(*process(Process1Config(), Worker1Config()))

    launcher.add_process(
        *process(Process2Config(), Worker2_1Config(), Worker2_2Config())
    )

    launcher.run()
    launcher.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
