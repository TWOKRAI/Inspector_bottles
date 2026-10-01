# -*- coding: utf-8 -*-
"""Конфиг CodeReaderPlugin — identity + register_bindings.

Все параметры живут в `registers.py` (V3_MY_PURE, как у ModbusPlugin). SHM-слот
не объявляется: наружу уходит строка кода, а не кадр — `memory` не нужен.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from Services.code_reader.plugin.registers import CodeReaderRegisters


@register_schema("CodeReaderPluginConfigV1")
class CodeReaderPluginConfig(PluginConfig):
    """Конфиг плагина считывателя кодов — identity + привязка register."""

    plugin_class: str = "Services.code_reader.plugin.plugin.CodeReaderPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [CodeReaderRegisters]
