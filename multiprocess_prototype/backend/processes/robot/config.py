"""Robot service configuration."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema
from multiprocess_framework.modules.process_module import (
    ProcessLaunchConfig,
    ProcessPriorityLevel,
)
from pydantic import Field


@register_schema("RobotConfigV3")
class RobotConfig(ProcessLaunchConfig):
    process_name: str = "robot"
    process_class: str = "multiprocess_prototype.backend.processes.robot.process.RobotProcess"
    priority: ProcessPriorityLevel = ProcessPriorityLevel.LOW
    queues: dict = Field(
        default_factory=lambda: {"system": {"maxsize": 50}, "data": {"maxsize": 20}}
    )
    log_file: str = "./robot_actions.log"
    reject_delay: Annotated[float, FieldMeta("Delay before rejection, sec", min=0.0, max=5.0)] = 0.5
