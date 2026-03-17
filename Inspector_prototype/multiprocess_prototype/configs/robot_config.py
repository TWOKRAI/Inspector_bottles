# multiprocess_prototype\configs\robot_config.py
"""
Конфигурация симулятора робота (RobotSimulatorProcess).

ProcessConfigBase + FieldMeta. class_path_from_type, ProcessPriorityLevel, queues.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)
from multiprocess_framework.refactored.modules.process_module import ProcessPriorityLevel
from pydantic import Field

from multiprocess_prototype.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.processes.robot_simulator_process import RobotSimulatorProcess


@register_schema("RobotConfig")
class RobotConfig(ProcessConfigBase):
    """Конфигурация симулятора робота."""

    process_name: str = "robot"
    class_path: str = class_path_from_type(RobotSimulatorProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.LOW
    queues: dict = Field(default_factory=lambda: {"system": {"maxsize": 50}, "data": {"maxsize": 20}})
    log_file: str = "./robot_actions.log"
    reject_delay: Annotated[
        float, FieldMeta("Задержка отбраковки, сек", min=0.0, max=5.0)
    ] = 0.5
