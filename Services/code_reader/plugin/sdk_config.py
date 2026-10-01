# -*- coding: utf-8 -*-
"""Конфиг CodeReaderSdkPlugin — identity + register_bindings.

Все параметры живут в `sdk_registers.py`. SHM-слот не объявляется: он выделяется
лениво на первом кадре (`frame_shm_middleware`), как у рецептов `hikvision_*`.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from Services.code_reader.plugin.sdk_registers import CodeReaderSdkRegisters


@register_schema("CodeReaderSdkPluginConfigV1")
class CodeReaderSdkPluginConfig(PluginConfig):
    """Конфиг SDK-плагина считывателя кодов — identity + привязка register."""

    plugin_class: str = "Services.code_reader.plugin.sdk_plugin.CodeReaderSdkPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [CodeReaderSdkRegisters]
