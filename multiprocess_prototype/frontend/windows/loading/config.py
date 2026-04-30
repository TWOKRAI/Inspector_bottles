# multiprocess_prototype/frontend/windows/loading/config.py
"""Конфиг окна загрузки (framework LoadingWindow)."""

from typing import Optional

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema


@register_schema("LoadingWindowConfig")
class LoadingWindowConfig(SchemaBase):
    title: str = "Загрузка..."
    min_width: int = 400
    min_height: int = 300
    logo_path: Optional[str] = None
