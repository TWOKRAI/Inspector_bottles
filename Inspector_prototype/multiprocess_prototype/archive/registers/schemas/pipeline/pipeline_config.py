# -*- coding: utf-8 -*-
"""Корневая схема пайплайна: камеры → регионы → обработки."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import Field, model_validator

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema

from .camera import Camera


@register_schema("PipelineConfig")
class PipelineConfig(SchemaBase):
    """
    Корень: камеры → регионы → обработки.

    Корневой ключ ``crop_regions`` (legacy) мигрирует в ``cameras``.
    """

    cameras: Dict[str, Camera] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        from .migration import migrate_legacy_pipeline_root

        return migrate_legacy_pipeline_root(data)
