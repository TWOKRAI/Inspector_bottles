# -*- coding: utf-8 -*-
"""Плагины считывателя кодов ID3000 для multiprocess_prototype (TCP и SDK)."""

from __future__ import annotations

from Services.code_reader.plugin.config import CodeReaderPluginConfig
from Services.code_reader.plugin.plugin import CodeReaderPlugin
from Services.code_reader.plugin.registers import CodeReaderRegisters
from Services.code_reader.plugin.sdk_config import CodeReaderSdkPluginConfig
from Services.code_reader.plugin.sdk_plugin import CodeReaderSdkPlugin
from Services.code_reader.plugin.sdk_registers import CodeReaderSdkRegisters

__all__ = [
    "CodeReaderPlugin",
    "CodeReaderPluginConfig",
    "CodeReaderRegisters",
    "CodeReaderSdkPlugin",
    "CodeReaderSdkPluginConfig",
    "CodeReaderSdkRegisters",
]
