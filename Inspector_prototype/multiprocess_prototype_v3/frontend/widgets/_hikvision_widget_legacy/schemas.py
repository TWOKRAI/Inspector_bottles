# multiprocess_prototype_v3/frontend/widgets/hikvision_widget/schemas.py
"""Схема UI для Hikvision: устройство, grabbing, параметры."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, Tuple

from pydantic import Field, model_validator

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


def _default_hikvision_api_map() -> List["HikvisionApiMapEntry"]:
    """Тройка API ↔ поля регистра по умолчанию."""
    return [
        HikvisionApiMapEntry(
            api_key="frame_rate",
            register_field="hikvision_frame_rate",
            parse_empty_default=25.0,
            line_edit_format_spec=".1f",
        ),
        HikvisionApiMapEntry(
            api_key="exposure_time",
            register_field="hikvision_exposure_time",
            parse_empty_default=10000.0,
            line_edit_format_spec=".0f",
        ),
        HikvisionApiMapEntry(
            api_key="gain",
            register_field="hikvision_gain",
            parse_empty_default=0.0,
            line_edit_format_spec=".1f",
        ),
    ]


def _default_hikvision_spinbox_rows() -> List["HikvisionSpinboxRow"]:
    """Конфиг строк NumericControl/spinbox для fps, exposure, gain."""
    return [
        HikvisionSpinboxRow(
            register_field="hikvision_frame_rate",
            label_attribute="label_frame_rate",
            min_val=0.1,
            max_val=120.0,
            read_fallback_default=25.0,
        ),
        HikvisionSpinboxRow(
            register_field="hikvision_exposure_time",
            label_attribute="label_exposure",
            min_val=0.0,
            max_val=1_000_000.0,
            read_fallback_default=10000.0,
        ),
        HikvisionSpinboxRow(
            register_field="hikvision_gain",
            label_attribute="label_gain",
            min_val=0.0,
            max_val=24.0,
            read_fallback_default=0.0,
        ),
    ]


@register_schema("HikvisionApiMapEntry")
class HikvisionApiMapEntry(SchemaBase):
    """Ключ API ↔ поле регистра."""

    api_key: str = "frame_rate"
    register_field: str = "hikvision_frame_rate"
    parse_empty_default: float = 0.0
    line_edit_format_spec: str = ".1f"


@register_schema("HikvisionSpinboxRow")
class HikvisionSpinboxRow(SchemaBase):
    """Строка spinbox: регистр, подпись, min/max, default."""

    register_field: str = "hikvision_frame_rate"
    label_attribute: str = "label_frame_rate"
    min_val: float = 0.0
    max_val: float = 100.0
    read_fallback_default: float = 0.0


@register_schema("HikvisionUiConfig")
class HikvisionUiConfig(SchemaBase):
    """Подписи и сопоставления для Hikvision."""

    group_device: str = "Устройство"
    device_combo_placeholder: str = "— выберите устройство —"
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
    label_frame_rate: str = "Frame Rate:"
    label_exposure: str = "Exposure:"
    label_gain: str = "Gain:"
    placeholder_fps: str = "FPS"
    placeholder_exposure: str = "μs"
    placeholder_gain: str = "dB"
    btn_get_parameters: str = "Get Parameters"
    btn_set_parameters: str = "Set Parameters"

    hikvision_line_edit_max_width: int = 80
    hikvision_api_to_register: List[HikvisionApiMapEntry] = Field(
        default_factory=_default_hikvision_api_map
    )
    hikvision_spinbox_rows: List[HikvisionSpinboxRow] = Field(
        default_factory=_default_hikvision_spinbox_rows
    )

    touch_keyboard: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta(
            "Touch-клавиатура для NumericControl spinbox",
            info="Перекрывает глобальный и camera_tab; mode: mini | full.",
        ),
    ] = Field(default=None)

    @model_validator(mode="after")
    def _validate_lengths(self) -> "HikvisionUiConfig":
        """Согласованность длин списков и допустимых label_attribute."""
        if len(self.hikvision_api_to_register) != len(self.hikvision_spinbox_rows):
            raise ValueError(
                "hikvision_api_to_register и hikvision_spinbox_rows должны быть одинаковой длины."
            )
        valid = {"label_frame_rate", "label_exposure", "label_gain"}
        for row in self.hikvision_spinbox_rows:
            if row.label_attribute not in valid:
                raise ValueError(f"label_attribute '{row.label_attribute}' не в {valid}")
        return self

    def hikvision_api_field_pairs(self) -> Tuple[Tuple[str, str], ...]:
        """Пары (api_key, register_field) для записи ответа камеры в регистр."""
        return tuple((m.api_key, m.register_field) for m in self.hikvision_api_to_register)

    def spinbox_label_for_row(self, row: HikvisionSpinboxRow) -> str:
        """Текст подписи NumericControl по атрибуту HikvisionUiConfig (label_frame_rate и т.д.)."""
        return str(getattr(self, row.label_attribute, row.label_attribute))
