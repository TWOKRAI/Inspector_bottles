"""Конфиг MLInferencePlugin — привязка register-схемы для GUI discovery."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import MLInferenceRegisters


@register_schema("MLInferencePluginConfigV1")
class MLInferenceConfig(PluginConfig):
    """Конфиг плагина инференса нейросети.

    Параметры tunable через register MLInferenceRegisters (инспектор Pipeline);
    здесь дублируются дефолты для рецепта.
    """

    plugin_class: str = "Services.ml_inference.plugin.plugin.MLInferencePlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [MLInferenceRegisters]

    model: str = ""
    device: str = "cpu"
    confidence_threshold: float = 0.5
    top_k: int = 5
