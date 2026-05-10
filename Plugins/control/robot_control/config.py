"""Конфиг RobotControlPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

from .registers import RobotControlRegisters


@register_schema("RobotControlPluginConfigV1")
class RobotControlConfig(PluginConfig):
    """Конфиг плагина управления отбраковкой — identity + register binding.

    Все параметры (enabled, min_defect_area, delay, max_detections) — в RobotControlRegisters.
    """

    plugin_class: str = (
        "Plugins.control.robot_control.plugin.RobotControlPlugin"
    )

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RobotControlRegisters]
