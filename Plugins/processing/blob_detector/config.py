"""Конфиг BlobDetectorPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import PluginConfig

from .registers import BlobDetectorRegisters


@register_schema("BlobDetectorPluginConfigV1")
class BlobDetectorConfig(PluginConfig):
    """Конфиг плагина детекции цветных контуров — identity + register binding.

    Все параметры (HSV, area, contours) — в BlobDetectorRegisters.
    """

    plugin_class: str = (
        "Plugins.processing.blob_detector.plugin.BlobDetectorPlugin"
    )

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [BlobDetectorRegisters]
