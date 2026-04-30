"""Application settings register schema — scaling + SHM budget parameters (Phase 0)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

from ..camera.policy import DEFAULT_CAMERA_TYPE, CameraTypeStr
from ..constants import SETTINGS_ROUTING


@register_schema("AppSettingsRegistersV3")
class AppSettingsRegisters(SchemaBase):
    """Профиль настроек приложения (AD-1, AD-3, AD-6).

    Определяет масштаб пайплайна — число камер, размер SHM ring-buffer, потолок бюджета
    разделяемой памяти, число воркеров на процесс-процессор, дефолтный источник камеры.
    SettingsProfileManager переключает этот регистр при смене профиля.
    """

    camera_count: Annotated[
        int,
        FieldMeta(
            "Число камер",
            info="Активные камеры в профиле (AD-1).",
            min=1,
            max=16,
            routing=SETTINGS_ROUTING,
        ),
    ] = 1

    ring_buffer_size: Annotated[
        int,
        FieldMeta(
            "Ring-buffer (K)",
            info="SHM-слотов на камеру для fan-out без копирования (AD-6).",
            min=2,
            max=8,
            routing=SETTINGS_ROUTING,
        ),
    ] = 3

    shm_budget_mb: Annotated[
        int,
        FieldMeta(
            "Бюджет SHM",
            info="Суммарный лимит разделяемой памяти в МБ (AD-6).",
            min=64,
            max=4096,
            unit="MB",
            routing=SETTINGS_ROUTING,
        ),
    ] = 512

    workers_per_processor: Annotated[
        int,
        FieldMeta(
            "Воркеров на процессор",
            info="Потоков ThreadPoolExecutor внутри Processor_{id} (AD-3).",
            min=1,
            max=8,
            routing=SETTINGS_ROUTING,
        ),
    ] = 2

    display_count: Annotated[
        int,
        FieldMeta(
            "Число окон",
            info="Окон отображения по умолчанию (0..N, AD-4).",
            min=0,
            max=16,
            routing=SETTINGS_ROUTING,
        ),
    ] = 2

    camera_source_type: Annotated[
        CameraTypeStr,
        FieldMeta(
            "Источник камер",
            info="Тип источника по умолчанию: simulator / webcam / hikvision.",
            routing=SETTINGS_ROUTING,
        ),
    ] = DEFAULT_CAMERA_TYPE


__all__ = ["AppSettingsRegisters"]
