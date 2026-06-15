"""Конфиг ControlPanelPlugin — источник-«Пульт» (GUI-контролы → сигналы)."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import PluginConfig
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import register_schema

from .registers import ControlPanelRegisters


@register_schema("ControlPanelPluginConfigV1")
class ControlPanelConfig(PluginConfig):
    """Конфиг пульта: набор контролов + размер пула выходных портов.

    Источник без кадров: SHM не используется (memory=None из базы). produce()
    лишь дренит накопленные эмиты контролов в items на выходные порты out_1..out_N.
    """

    plugin_class: str = "Services.control_panel.plugin.plugin.ControlPanelPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [ControlPanelRegisters]

    panel_id: Annotated[
        str,
        FieldMeta(description="ID пульта (метка для логов/state)"),
    ] = "pult"

    controls: Annotated[
        list[dict[str, Any]],
        FieldMeta(description="Список контролов (id/type/label/port/min/max/step/value)"),
    ] = []

    port_count: Annotated[
        int,
        FieldMeta(description="Число выходных портов пула (out_1..out_N)"),
    ] = 8
