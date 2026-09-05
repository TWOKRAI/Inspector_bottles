# -*- coding: utf-8 -*-
"""Конфиг OtelExportPlugin — identity + привязка регистров.

По образцу `Plugins/io/telemetry_sink/config.py`: все параметры живут в
`registers.py` (а через него — в схеме сервиса), конфиг несёт только identity
для discovery и `register_bindings`.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import OtelExportRegisters

__all__ = ["OtelExportPluginConfig"]


@register_schema("OtelExportPluginConfigV1")
class OtelExportPluginConfig(PluginConfig):
    """Конфиг экспортёра OTLP — identity + register binding.

    `plugin_class` указывает на класс, которого ещё НЕТ: `plugin.py` пишется в
    Ф2.1. Это строка dotted-path, импорт по ней делает `class_loader` при сборке
    топологии, поэтому контракт можно объявить раньше реализации — но подключать
    фрагмент топологии до Ф2 нельзя: процесс не поднимется.
    """

    plugin_class: str = "Plugins.io.otel_export.plugin.OtelExportPlugin"

    #: Привязка к register-классам (дверь конфига плагина).
    register_bindings: ClassVar[list[type[SchemaBase]]] = [OtelExportRegisters]
