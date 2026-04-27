"""Схемы конфигурации виджета индикатора записи."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("RecordingIndicatorConfigV3")
class RecordingIndicatorConfig(SchemaBase):
    """Конфигурация виджета индикатора записи."""

    blink_interval_ms: Annotated[
        int,
        FieldMeta(
            "Интервал мигания",
            info="Интервал мигания красной точки при активной записи (мс).",
            min=100,
            max=5000,
            unit="мс",
        ),
    ] = 500


__all__ = ["RecordingIndicatorConfig"]
