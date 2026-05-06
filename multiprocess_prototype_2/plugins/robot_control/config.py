"""Конфиг RobotControlPlugin — параметры управления отбраковкой."""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("RobotControlPluginConfigV1")
class RobotControlConfig(PluginConfig):
    """Конфиг плагина управления отбраковкой.

    Processing: вход detections → решение reject/pass → выход inspection_result.
    Параметры фильтрации дефектов и задержки отбраковки.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.robot_control.plugin.RobotControlPlugin"
    )
    plugin_name: str = "robot_control"
    category: str = "processing"

    # Флаг включения отбраковки
    enabled: Annotated[
        bool, FieldMeta(description="Включена ли отбраковка")
    ] = True

    # Минимальная площадь дефекта для reject
    min_defect_area: Annotated[
        int, FieldMeta(description="Минимальная площадь дефекта для reject (пикселей)")
    ] = 500

    # Задержка отбраковки
    reject_delay_ms: Annotated[
        int, FieldMeta(description="Задержка отбраковки (мс)")
    ] = 0

    # Максимум детекций для reject (0 = любое количество)
    max_detections_for_reject: Annotated[
        int, FieldMeta(description="Максимум детекций для reject (0 = любое количество)")
    ] = 0

    @property
    def memory(self) -> None:
        """Нет SHM — плагин работает только с данными."""
        return None
