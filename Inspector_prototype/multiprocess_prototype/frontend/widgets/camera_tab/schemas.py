# -*- coding: utf-8 -*-
"""
Конфиг вкладки «Камера»: подписи UI, числовые пределы, сопоставления API ↔ регистр.

Единая точка настройки для фронта (SchemaBase / register_schema). Меняйте значения здесь
или через ``model_validate``/конфиг приложения — без правок в ``widget.py``.
"""
from __future__ import annotations

from typing import Annotated, Dict, List, Tuple

from pydantic import Field, model_validator

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


def _default_camera_type_register_ids() -> List[str]:
    return ["simulator", "webcam", "hikvision"]


def _default_camera_type_labels() -> List[str]:
    return ["Simulator", "Webcam", "Hikvision"]


def _default_hikvision_api_map() -> List["CameraTabHikvisionApiMapEntry"]:
    return [
        CameraTabHikvisionApiMapEntry(
            api_key="frame_rate",
            register_field="hikvision_frame_rate",
            parse_empty_default=25.0,
            line_edit_format_spec=".1f",
        ),
        CameraTabHikvisionApiMapEntry(
            api_key="exposure_time",
            register_field="hikvision_exposure_time",
            parse_empty_default=10000.0,
            line_edit_format_spec=".0f",
        ),
        CameraTabHikvisionApiMapEntry(
            api_key="gain",
            register_field="hikvision_gain",
            parse_empty_default=0.0,
            line_edit_format_spec=".1f",
        ),
    ]


def _default_hikvision_spinbox_rows() -> List["CameraTabHikvisionSpinboxRow"]:
    """Порядок строк = порядок полей в fallback line edit и чтении triple из регистра."""
    return [
        CameraTabHikvisionSpinboxRow(
            register_field="hikvision_frame_rate",
            label_attribute="label_frame_rate",
            min_val=0.1,
            max_val=120.0,
            read_fallback_default=25.0,
        ),
        CameraTabHikvisionSpinboxRow(
            register_field="hikvision_exposure_time",
            label_attribute="label_exposure",
            min_val=0.0,
            max_val=1_000_000.0,
            read_fallback_default=10000.0,
        ),
        CameraTabHikvisionSpinboxRow(
            register_field="hikvision_gain",
            label_attribute="label_gain",
            min_val=0.0,
            max_val=24.0,
            read_fallback_default=0.0,
        ),
    ]


@register_schema("CameraTabHikvisionApiMapEntry")
class CameraTabHikvisionApiMapEntry(SchemaBase):
    """Ключ в словаре от бэкенда ↔ поле регистра; формат fallback line edit."""

    api_key: Annotated[
        str,
        FieldMeta("Ключ API", info="update_camera_parameters, ответ Get Parameters."),
    ] = "frame_rate"
    register_field: Annotated[
        str,
        FieldMeta("Поле регистра", info="Имя поля в CameraRegisters."),
    ] = "hikvision_frame_rate"
    parse_empty_default: Annotated[
        float,
        FieldMeta("Значение по умолчанию", info="Если в QLineEdit пусто при Set."),
    ] = 0.0
    line_edit_format_spec: Annotated[
        str,
        FieldMeta("Формат отображения", info="Спецификатор для format(val, spec), напр. .1f"),
    ] = ".1f"


@register_schema("CameraTabHikvisionSpinboxRow")
class CameraTabHikvisionSpinboxRow(SchemaBase):
    """Одна строка spinbox Hikvision: регистр, подпись (атрибут родителя), min/max, default при чтении."""

    register_field: Annotated[str, FieldMeta("Поле регистра")] = "hikvision_frame_rate"
    label_attribute: Annotated[
        str,
        FieldMeta("Подпись", info="Имя поля в CameraTabUiConfig, напр. label_frame_rate."),
    ] = "label_frame_rate"
    min_val: float = 0.0
    max_val: float = 100.0
    read_fallback_default: Annotated[
        float,
        FieldMeta("Значение по умолчанию", info="Если в регистре нет поля."),
    ] = 0.0


@register_schema("CameraTabUiConfig")
class CameraTabUiConfig(SchemaBase):
    """Подписи, размеры, сопоставления типа камеры и Hikvision."""

    # --- Тип камеры: порядок элементов QComboBox и значения camera_type в регистре ---
    camera_type_register_ids: Annotated[
        List[str],
        FieldMeta(
            "ID типа камеры",
            info="По индексу согласованы с camera_type_options (одинаковая длина и порядок).",
        ),
    ] = Field(default_factory=_default_camera_type_register_ids)

    camera_type_options: List[str] = Field(
        default_factory=_default_camera_type_labels,
        description="Тексты элементов QComboBox (порядок = camera_type_register_ids).",
    )

    camera_type_combo_min_width: Annotated[
        int,
        FieldMeta("Ширина комбобокса типа", info="Минимальная ширина в пикселях."),
    ] = 180

    #: Значение ``camera_type``, при котором показывается вторая страница стека (Hikvision).
    camera_type_id_for_hikvision_page: Annotated[
        str,
        FieldMeta("ID страницы Hikvision", info="Должен совпадать с одним из camera_type_register_ids."),
    ] = "hikvision"

    group_camera_type: Annotated[
        str,
        FieldMeta("Тип камеры", info="Заголовок группы выбора типа."),
    ] = "Тип камеры"

    group_sim_control: Annotated[
        str,
        FieldMeta("Управление камерой", info="Simulator / Webcam: Start/Stop."),
    ] = "Управление камерой"

    btn_start: Annotated[str, FieldMeta("Start")] = "▶ Start"
    btn_stop: Annotated[str, FieldMeta("Stop")] = "■ Stop"

    group_fps: Annotated[str, FieldMeta("FPS")] = "FPS"
    fps_numeric_control_label: Annotated[
        str,
        FieldMeta("Подпись FPS (control_v2)", info="NumericControl при привязке к регистру."),
    ] = "FPS"
    initial_fps: Annotated[
        int,
        FieldMeta("Начальный FPS", info="Значение слайдера при открытии (fallback)."),
    ] = 25
    fps_suffix: Annotated[str, FieldMeta("Суффикс FPS")] = " FPS"
    fps_slider_min: Annotated[int, FieldMeta("Мин. FPS (слайдер без регистра)")] = 1
    fps_slider_max: Annotated[int, FieldMeta("Макс. FPS (слайдер без регистра)")] = 60

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

    hikvision_line_edit_max_width: Annotated[
        int,
        FieldMeta("Ширина QLineEdit", info="Fallback-параметры без RegistersManager."),
    ] = 80

    hikvision_api_to_register: List[CameraTabHikvisionApiMapEntry] = Field(
        default_factory=_default_hikvision_api_map,
        description="Словарь от бэкенда → поля регистра; порядок = порядок строк fallback UI.",
    )

    hikvision_spinbox_rows: List[CameraTabHikvisionSpinboxRow] = Field(
        default_factory=_default_hikvision_spinbox_rows,
        description="Строки NumericControl / fallback; register_field согласован с api map.",
    )

    @model_validator(mode="after")
    def _validate_camera_type_lengths(self) -> "CameraTabUiConfig":
        if len(self.camera_type_register_ids) != len(self.camera_type_options):
            raise ValueError(
                "camera_type_register_ids и camera_type_options должны быть одинаковой длины."
            )
        if len(self.hikvision_api_to_register) != len(self.hikvision_spinbox_rows):
            raise ValueError(
                "hikvision_api_to_register и hikvision_spinbox_rows должны быть одинаковой длины."
            )
        valid_labels = {"label_frame_rate", "label_exposure", "label_gain"}
        for row in self.hikvision_spinbox_rows:
            if row.label_attribute not in valid_labels:
                raise ValueError(
                    f"label_attribute '{row.label_attribute}' не найден в CameraTabUiConfig; "
                    f"допустимы: {valid_labels}"
                )
        return self

    def camera_type_index_map(self) -> Dict[str, int]:
        """Значение camera_type для регистра → индекс в QComboBox."""
        return {rid: i for i, rid in enumerate(self.camera_type_register_ids)}

    def camera_type_for_combo_index(self, index: int) -> str:
        """Индекс QComboBox → строка camera_type."""
        ids = self.camera_type_register_ids
        if not ids:
            return "simulator"
        if 0 <= index < len(ids):
            return ids[index]
        return ids[0]

    def hikvision_api_field_pairs(self) -> Tuple[Tuple[str, str], ...]:
        """(api_key, register_field) для записи в регистр."""
        return tuple((m.api_key, m.register_field) for m in self.hikvision_api_to_register)

    def spinbox_label_for_row(self, row: CameraTabHikvisionSpinboxRow) -> str:
        return str(getattr(self, row.label_attribute, row.label_attribute))


def default_tab_item():
    from ..tabs.tab_item_config import TabItemConfig

    return TabItemConfig(id="camera", title="Камера", widget="camera")
