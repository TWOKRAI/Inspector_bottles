# -*- coding: utf-8 -*-
"""
Строки и подписи UI вкладки «Камера».

Только фронт. Поведение вкладки без текстов — см. `CameraTabConfig`.
"""
from __future__ import annotations

from typing import Annotated, List

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CameraTabUiConfig")
class CameraTabUiConfig(SchemaBase):
    """Подписи групп, кнопок и полей вкладки камеры."""

    group_camera_type: Annotated[
        str,
        FieldMeta("Тип камеры", info="Заголовок группы выбора типа."),
    ] = "Тип камеры"

    camera_type_options: List[str] = Field(
        default_factory=lambda: ["Simulator", "Webcam", "Hikvision"],
        description="Элементы QComboBox типа камеры",
    )

    group_sim_control: Annotated[
        str,
        FieldMeta("Управление камерой", info="Simulator / Webcam: Start/Stop."),
    ] = "Управление камерой"

    btn_start: Annotated[str, FieldMeta("Start")] = "▶ Start"
    btn_stop: Annotated[str, FieldMeta("Stop")] = "■ Stop"

    group_fps: Annotated[str, FieldMeta("FPS")] = "FPS"
    initial_fps: Annotated[
        int,
        FieldMeta("Начальный FPS", info="Значение слайдера при открытии."),
    ] = 25
    fps_suffix: Annotated[str, FieldMeta("Суффикс FPS")] = " FPS"

    group_device: Annotated[str, FieldMeta("Устройство", info="Hikvision: выбор устройства.")] = (
        "Устройство"
    )
    device_combo_placeholder: Annotated[
        str,
        FieldMeta("Плейсхолдер списка устройств"),
    ] = "— выберите устройство —"
    btn_enum_devices: Annotated[str, FieldMeta("Enum Devices")] = "Enum Devices"
    btn_open: Annotated[str, FieldMeta("Open")] = "Open"
    btn_close: Annotated[str, FieldMeta("Close")] = "Close"

    group_grabbing: Annotated[str, FieldMeta("Grabbing")] = "Grabbing"
    btn_start_grabbing: Annotated[str, FieldMeta("Start Grabbing")] = "▶ Start Grabbing"
    btn_stop_grabbing: Annotated[str, FieldMeta("Stop Grabbing")] = "■ Stop Grabbing"

    group_params: Annotated[str, FieldMeta("Параметры камеры", info="Hikvision.")] = (
        "Параметры камеры"
    )
    label_frame_rate: Annotated[str, FieldMeta("Метка Frame Rate")] = "Frame Rate:"
    label_exposure: Annotated[str, FieldMeta("Метка Exposure")] = "Exposure:"
    label_gain: Annotated[str, FieldMeta("Метка Gain")] = "Gain:"
    placeholder_fps: Annotated[str, FieldMeta("Плейсхолдер FPS")] = "FPS"
    placeholder_exposure: Annotated[str, FieldMeta("Плейсхолдер exposure")] = "μs"
    placeholder_gain: Annotated[str, FieldMeta("Плейсхолдер gain")] = "dB"
    btn_get_parameters: Annotated[str, FieldMeta("Get Parameters")] = "Get Parameters"
    btn_set_parameters: Annotated[str, FieldMeta("Set Parameters")] = "Set Parameters"
