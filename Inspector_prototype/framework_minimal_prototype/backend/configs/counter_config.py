# framework_minimal_prototype\backend\configs\counter_config.py
"""Конфиг единственного процесса-счётчика."""

from multiprocess_framework.modules.process_module import ProcessPriorityLevel

from framework_minimal_prototype.backend.configs.base_config import (
    ProcessConfigBase,
    class_path_from_type,
)
from framework_minimal_prototype.backend.processes.counter_process import CounterProcess


class CounterConfig(ProcessConfigBase):
    process_name: str = "counter"
    class_path: str = class_path_from_type(CounterProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.NORMAL
