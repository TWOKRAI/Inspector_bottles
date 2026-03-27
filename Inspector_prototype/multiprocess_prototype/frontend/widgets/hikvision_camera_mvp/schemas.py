# multiprocess_prototype/frontend/widgets/hikvision_camera_mvp/schemas.py
"""UI-конфиг Hikvision MVP: группы, кнопки, touch_keyboard, опциональные оверрайды отображения."""

from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("HikvisionCameraMvpUiConfig")
class HikvisionCameraMvpUiConfig(SchemaBase):
    """Тексты и разметка. Границы параметров — в CameraRegisters; здесь только UI и overrides."""

    group_device: str = "Устройство"
    device_list_hint: Annotated[
        str,
        FieldMeta("Подсказка", info="Текст над списком устройств."),
    ] = "Список камер (кнопка Enum). При большом числе устройств используйте прокрутку."
    device_list_min_height: Annotated[
        int,
        FieldMeta("Высота списка", info="Минимальная высота списка устройств, px."),
    ] = 120
    btn_enum_devices: str = "Enum Devices"
    btn_open: str = "Open"
    btn_close: str = "Close"

    group_grabbing: str = "Grabbing"
    btn_start_grabbing: str = "Start Grabbing"
    btn_stop_grabbing: str = "Stop Grabbing"

    group_params: str = "Параметры камеры"
    btn_get_parameters: str = "Get Parameters"
    btn_set_parameters: str = "Set Parameters"

    hikvision_line_edit_max_width: int = 80

    param_display: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Опционально: имя поля регистра (hikvision_frame_rate, …) → "
            "{placeholder, format_spec, label} для переопределения дефолтов."
        ),
    )

    touch_keyboard: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для NumericControl spinbox",
            info="Перекрывает глобальный и camera_tab; mode: mini | full.",
        ),
    ] = Field(default=None)
