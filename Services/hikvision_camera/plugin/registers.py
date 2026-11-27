"""Register камеры Hikvision: поля ядра `camera_device` плюс вендорские параметры MVS.

Порядок объявления полей = порядок записи плана в прибор (`params.build_plan`): `exposure_auto`
(в базе) идёт раньше `exposure_time`, `frame_rate_enable` — раньше `frame_rate`. Ключи таблицы привязки
`driver.BINDINGS` обязаны быть полями этого класса (ключ без поля молча игнорируется).
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema
from Services.camera_device.registers_base import CameraDeviceRegisters


@register_schema("HikvisionCameraRegistersV1")
class HikvisionCameraRegisters(CameraDeviceRegisters):
    """Параметры камеры Hikvision (MVS SDK) поверх общего register'а ядра."""

    # Переобъявление базового поля ради имени в интроспекции: порт плагин берёт в `create_port` и это поле не читает.
    driver: Annotated[
        str,
        FieldMeta(description="Драйвер", info="Имя драйвера порта; плагин hikvision всегда работает через mvs"),
    ] = "mvs"

    # Переобъявление базового поля: позиция в плане остаётся базовой (после `exposure_auto`), меняется только политика.
    exposure_time: Annotated[
        float,
        FieldMeta(
            description="Время экспозиции (мкс)",
            min=10.0,
            max=1_000_000.0,
            unit="мкс",
            apply="restart",
            enabled_if={"exposure_auto": ["Off"]},
        ),
    ] = 10_000.0

    # Родитель раньше потомка: `gain_auto` объявлен перед `gain` (порядок объявления = порядок плана записи).
    gain_auto: Annotated[
        Literal["Off", "Once", "Continuous"],
        FieldMeta(description="Автоусиление", apply="restart"),
    ] = "Off"

    gain: Annotated[
        float,
        FieldMeta(
            description="Усиление (дБ)",
            min=0.0,
            max=24.0,
            unit="дБ",
            apply="restart",
            enabled_if={"gain_auto": ["Off"]},
        ),
    ] = 0.0

    frame_rate_enable: Annotated[
        bool,
        FieldMeta(description="Ограничить частоту кадров"),
    ] = False

    frame_rate: Annotated[
        float,
        FieldMeta(
            description="Частота кадров (fps)",
            min=1.0,
            max=120.0,
            unit="fps",
            apply="restart",
            enabled_if={"frame_rate_enable": [True]},
        ),
    ] = 25.0

    # Группа packet: `packet_managed=False` — поля не пишутся (драйвер пишет 0 как «оптимальный», а чтение даёт
    # другое число: ложный param_errors на каждом take_device).
    packet_managed: Annotated[
        bool,
        FieldMeta(
            description="Управлять размером пакета", info="Выкл — узлы GigE-пакета не трогаются", ui_group="packet"
        ),
    ] = False

    packet_size: Annotated[
        int,
        FieldMeta(description="Размер пакета GigE, байт", ui_group="packet"),
    ] = 1500

    packet_delay: Annotated[
        int,
        FieldMeta(description="Задержка между пакетами GigE", ui_group="packet"),
    ] = 0

    # --- Размер кадра на выходе: слот SHM = (resolution_height, resolution_width, 3) ---
    resolution_width: Annotated[
        int,
        FieldMeta(description="Ширина кадра на выходе, px", apply="config", min=1),
    ] = 1440

    resolution_height: Annotated[
        int,
        FieldMeta(description="Высота кадра на выходе, px", apply="config", min=1),
    ] = 1080

    resize_mode: Annotated[
        Literal["letterbox", "stretch"],
        FieldMeta(
            description="Режим ресайза",
            info="letterbox — с сохранением аспекта и чёрными полями; stretch — анаморфно",
            apply="config",
        ),
    ] = "letterbox"
