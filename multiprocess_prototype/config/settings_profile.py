"""Валидированный профиль настроек приложения (Task 1.2).

Оборачивает сырой dict из YAML в типизированную Pydantic-модель с ограничениями.
Невалидные значения (camera_count: -1, ring_buffer_size: 0) поднимают ValidationError
вместо silent undefined behavior.
"""

from __future__ import annotations

from typing import Literal

from multiprocess_framework.modules.data_schema_module import SchemaBase
from pydantic import Field


class SettingsProfile(SchemaBase):
    """Валидированный профиль настроек приложения.

    Поля соответствуют AppSettingsRegisters + worker_pool_size из AppConfig.
    Ограничения взяты из FieldMeta в registers/settings/schemas.py.
    """

    # Число активных камер в профиле (от 1 до 16)
    camera_count: int = Field(default=1, ge=1, le=16)

    # Размер SHM ring-buffer на камеру (минимум 2 — для корректного fan-out)
    ring_buffer_size: int = Field(default=3, ge=2, le=10)

    # Число worker-процессов в пуле (0 = пул отключён)
    worker_pool_size: int = Field(default=0, ge=0, le=8)

    # Тип источника камер по умолчанию
    camera_source_type: Literal["simulator", "webcam", "hikvision", "file"] = "simulator"


__all__ = ["SettingsProfile"]
