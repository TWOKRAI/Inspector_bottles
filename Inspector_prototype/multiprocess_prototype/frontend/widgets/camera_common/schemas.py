# multiprocess_prototype/frontend/widgets/camera_common/schemas.py
"""
Схема UI для Simulator/Webcam: Start/Stop, FPS (используется SimWebcamWidget и fps_section).
"""
from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("SimWebcamUiConfig")
class SimWebcamUiConfig(SchemaBase):
    """Подписи и пределы для Simulator/Webcam: управление и FPS."""

    group_sim_control: Annotated[
        str,
        FieldMeta("Управление камерой", info="Simulator / Webcam: Start/Stop."),
    ] = "Управление камерой"

    btn_start: Annotated[str, FieldMeta("Start")] = "▶ Start"
    btn_stop: Annotated[str, FieldMeta("Stop")] = "■ Stop"

    group_fps: Annotated[str, FieldMeta("FPS")] = "FPS"
    fps_numeric_control_label: Annotated[
        str,
        FieldMeta("Подпись FPS", info="NumericControl при привязке к регистру."),
    ] = "FPS"
    initial_fps: Annotated[int, FieldMeta("Начальный FPS")] = 25
    fps_suffix: Annotated[str, FieldMeta("Суффикс FPS")] = " FPS"
    fps_slider_min: Annotated[int, FieldMeta("Мин. FPS")] = 1
    fps_slider_max: Annotated[int, FieldMeta("Макс. FPS")] = 60
