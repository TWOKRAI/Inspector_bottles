"""
Конфигурация симулятора робота (RobotSimulatorProcess).

ProcessConfigBase + FieldMeta для валидации параметров.
build() — HasBuild для process() / add_process().
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.configs.base_config import ProcessConfigBase


@register_schema("RobotConfig")
class RobotConfig(ProcessConfigBase):
    """Конфигурация симулятора робота."""

    process_name: str = "robot"
    log_file: str = "./robot_actions.log"
    reject_delay: Annotated[
        float, FieldMeta("Задержка отбраковки, сек", min=0.0, max=5.0)
    ] = 0.5

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(RobotConfig()))."""
        proc_dict = self._build_proc_dict(
            "multiprocess_prototype.processes.robot_simulator_process.RobotSimulatorProcess",
            queues={"system": {"maxsize": 50}, "data": {"maxsize": 20}},
            priority="low",
        )
        return (self.process_name, proc_dict)
