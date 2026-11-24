"""FrameBufferRegisters — параметры плагина frame_buffer (буфер кадров в RAM).

Purpose: единый источник параметров и FieldMeta. Границы значений — только в FieldMeta
(Python-валидаторы в регистрах запрещены сторожем test_1b2d_no_python_validators_contract).

Умолчания ВРЕМЕННЫЕ, до замера 100 настоящих кадров (У5): `buffer_seconds` и `buffer_max_mb` —
предложение приложения 1 (раздел Д), не решение; `jpeg_quality` 85 — решение владельца 5.
Длина буфера приходит из рецепта; умолчание нужно только узлу без рецепта.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import FieldMeta, SchemaBase, register_schema

__all__ = ["FrameBufferRegisters"]


@register_schema("FrameBufferRegistersV1")
class FrameBufferRegisters(SchemaBase):
    """Параметры буфера кадров: длина по времени, потолок байт, бюджет пинов, качество JPEG."""

    buffer_seconds: Annotated[
        float,
        FieldMeta(
            "Buffer Seconds",
            info="Сколько секунд кадров держит буфер (по capture_ns). Умолчание временное, до замера 100 кадров",
            min=0.1,
            max=600,
            unit="с",
        ),
    ] = 60.0

    buffer_max_mb: Annotated[
        int,
        FieldMeta(
            "Buffer Max MB",
            info="Жёсткий потолок байт буфера. Умолчание временное, до замера 100 кадров",
            min=16,
            unit="МБ",
        ),
    ] = 1024

    pin_max_mb: Annotated[
        int,
        FieldMeta(
            "Pin Max MB",
            info="Бюджет закреплённых кадров; 0 = равен buffer_max_mb; больше buffer_max_mb не допускается",
            min=0,
            unit="МБ",
        ),
    ] = 0

    jpeg_quality: Annotated[
        int,
        FieldMeta(
            "JPEG Quality",
            info="Качество JPEG при кодировании кадра (1-100); 85 — решение владельца до замера 100 кадров",
            min=1,
            max=100,
        ),
    ] = 85
