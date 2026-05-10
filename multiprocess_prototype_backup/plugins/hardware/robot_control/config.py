"""Конфиг RobotPlugin — параметры робота."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("RobotPluginConfigV1")
class RobotPluginConfig(PluginConfig):
    """Конфиг плагина робота-отбраковщика.

    Output-плагин: принимает команды reject/pass → управляет оборудованием.
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.hardware.robot_control.plugin.RobotPlugin"
    )
    plugin_name: str = "robot"
    category: str = "output"

    # Параметры робота
    reject_delay: float = 0.5
    log_file: str = "./robot_actions.log"
