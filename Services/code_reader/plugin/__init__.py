# -*- coding: utf-8 -*-
"""Плагин считывателя кодов ID3000 для multiprocess_prototype."""

from __future__ import annotations

from Services.code_reader.plugin.config import CodeReaderPluginConfig
from Services.code_reader.plugin.plugin import CodeReaderPlugin
from Services.code_reader.plugin.registers import CodeReaderRegisters

__all__ = ["CodeReaderPlugin", "CodeReaderPluginConfig", "CodeReaderRegisters"]
