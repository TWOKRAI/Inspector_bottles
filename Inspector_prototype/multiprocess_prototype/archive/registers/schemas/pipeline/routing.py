# -*- coding: utf-8 -*-
"""
Маршрутизация полей пайплайна к процессору.

Должна совпадать с ``processing_tab.processor.PROCESSOR_ROUTING`` (без импорта
оттуда — иначе цикл processor → pipeline → routing → processor).
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import FieldRouting

PIPELINE_PARAMS_ROUTING = FieldRouting(channel="control_processor")

__all__ = ["PIPELINE_PARAMS_ROUTING"]
