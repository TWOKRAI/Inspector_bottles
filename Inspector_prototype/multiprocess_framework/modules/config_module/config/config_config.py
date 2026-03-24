"""
ConfigManagerConfig — конфигурационная схема ConfigManager.

Следует паттерну ChannelRoutingConfig(RegisterBase) + @register_schema,
принятому в архитектуре фреймворка (ADR-016).
"""
from typing import Annotated, Optional

from data_schema_module import SchemaBase, FieldMeta, register_schema


@register_schema("config_manager")
class ConfigManagerConfig(SchemaBase):
    """Конфигурация ConfigManager, регистрируется в реестре схем."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "ConfigManager"
    auto_sync: Annotated[bool, FieldMeta("Автосинхронизация с ConfigStore при shutdown")] = True
    validate_on_set: Annotated[bool, FieldMeta("Валидировать данные при каждом set()")] = False
    env_prefix: Annotated[Optional[str], FieldMeta("Префикс env-переменных по умолчанию")] = None
