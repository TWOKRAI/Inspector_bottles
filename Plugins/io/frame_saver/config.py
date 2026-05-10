"""Конфиг FrameSaverPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

from .registers import FrameSaverRegisters


@register_schema("FrameSaverPluginConfigV1")
class FrameSaverPluginConfig(PluginConfig):
    """Конфиг плагина сохранения кадров на диск — identity + register binding.

    Все параметры (output_dir, save_every_n, image_format, jpeg_quality) — в FrameSaverRegisters.
    """

    plugin_class: str = (
        "Plugins.io.frame_saver.plugin.FrameSaverPlugin"
    )

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [FrameSaverRegisters]
