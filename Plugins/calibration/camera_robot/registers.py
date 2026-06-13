"""CameraRobotCalibrationRegisters — live-параметры визарда калибровки."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CameraRobotCalibrationRegistersV1")
class CameraRobotCalibrationRegisters(SchemaBase):
    """Параметры калибровки. ID-поля — дефолты, переопределяются командой cal_begin."""

    robot_id: Annotated[str, FieldMeta("Robot ID", info="device_id робота в реестре devices")] = "robot_main"
    vfd_id: Annotated[str, FieldMeta("VFD ID", info="device_id ленты (ПЧ) в реестре devices")] = "vfd_belt"
    camera_id: Annotated[str, FieldMeta("Camera ID", info="ключ файла калибровки config/calibration/<id>.yaml")] = (
        "cam0"
    )
    expected_points: Annotated[
        int, FieldMeta("Точек эталона", info="кол-во кругов на плате (4 угла + центр)", min=5, max=5)
    ] = 5
    reproj_threshold_mm: Annotated[
        float, FieldMeta("Порог reproj", info="макс. ошибка перепроекции центра", min=0.1, max=50.0, unit="mm")
    ] = 2.0
