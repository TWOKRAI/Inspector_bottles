# -*- coding: utf-8 -*-
"""SharedResourcesManagerConfig — плоская схема фасада SharedResourcesManager."""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("shared_resources_manager")
class SharedResourcesManagerConfig(SchemaBase):
    """Параметры инициализации SharedResourcesManager (метаданные для UI/реестра)."""

    manager_name: Annotated[str, FieldMeta("Имя фасада")] = "SharedResourcesManager"
    auto_proxy: Annotated[bool, FieldMeta("ObservableMixin: авто-прокси")] = True
    observable_config: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Конфиг ObservableMixin (опционально)"),
    ] = None
