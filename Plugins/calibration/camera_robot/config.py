"""Конфиг CameraRobotCalibrationPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import CameraRobotCalibrationRegisters


@register_schema("CameraRobotCalibrationPluginConfigV1")
class CameraRobotCalibrationConfig(PluginConfig):
    """Конфиг плагина-оркестратора калибровки камера↔робот."""

    plugin_class: str = "Plugins.calibration.camera_robot.plugin.CameraRobotCalibrationPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [CameraRobotCalibrationRegisters]
