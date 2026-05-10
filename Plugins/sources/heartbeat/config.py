"""Конфигурация HeartbeatPlugin."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import (
    FieldMeta,
)
from multiprocess_framework.modules.process_module.generic.generic_process_config import (
    PluginConfig,
)


@register_schema("HeartbeatPluginConfigV1")
class HeartbeatPluginConfig(PluginConfig):
    """Конфиг heartbeat-плагина: интервал и сообщение."""

    plugin_class: str = (
        "Plugins.sources.heartbeat.plugin.HeartbeatPlugin"
    )

    interval_sec: Annotated[
        float,
        FieldMeta(description="Интервал между heartbeat-сообщениями (секунды)"),
    ] = 2.0

    message: Annotated[
        str,
        FieldMeta(description="Текст heartbeat-сообщения"),
    ] = "alive"
