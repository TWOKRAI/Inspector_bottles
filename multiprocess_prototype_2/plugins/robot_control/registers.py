"""RobotControlRegisters — все параметры robot_control плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase


@register_schema("RobotControlRegistersV1")
class RobotControlRegisters(SchemaBase):
    """Все параметры robot_control — управление отбраковкой."""

    # Флаг включения отбраковки
    enabled: Annotated[bool, FieldMeta(
        "Enabled", info="Включена ли отбраковка",
    )] = True

    # Минимальная площадь дефекта для reject
    min_defect_area: Annotated[int, FieldMeta(
        "Min Defect Area", info="Минимальная площадь дефекта для reject (пикселей)",
        min=0, unit="px²",
    )] = 500

    # Задержка отбраковки
    reject_delay_ms: Annotated[int, FieldMeta(
        "Reject Delay", info="Задержка отбраковки", unit="ms",
        min=0,
    )] = 0

    # Максимум детекций для reject (0 = любое количество)
    max_detections_for_reject: Annotated[int, FieldMeta(
        "Max Detections For Reject", info="Максимум детекций для reject (0 = любое количество)",
        min=0,
    )] = 0
