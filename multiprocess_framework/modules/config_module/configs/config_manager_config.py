# -*- coding: utf-8 -*-
"""
ConfigManagerConfig — единственная SchemaBase-схема модуля (реестр схем).

Рантайм (Config, ConfigManager) живёт в ``config_module/core/``.
"""
from typing import Annotated, Optional

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("config_manager")
class ConfigManagerConfig(SchemaBase):
    """Параметры инициализации/поведения ConfigManager для UI и сборки процессных конфигов."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "ConfigManager"
    auto_sync: Annotated[bool, FieldMeta("Автосинхронизация с ConfigStore при shutdown")] = True
    validate_on_set: Annotated[bool, FieldMeta("Валидировать данные при каждом set()")] = False
    env_prefix: Annotated[Optional[str], FieldMeta("Префикс env-переменных по умолчанию")] = None
