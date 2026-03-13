# -*- coding: utf-8 -*-
"""
ChannelRoutingConfig — базовый RegisterBase-конфиг для менеджеров маршрутизации.

Наследники расширяют для своих нужд:
    LoggerManagerConfig  — добавляет default_level, batch_size, scopes
    RouterManagerConfig  — добавляет send_queue_size, poll_interval
    ErrorManagerConfig   — добавляет severity channels, include_stacktrace

Общий контракт:
    build() → (manager_name: str, config_dict: dict)

    config_dict всегда содержит:
        channels:  Dict[str, dict]  — описание каналов
        ...specific fields...

    Используется normalize_config() для преобразования в dict.

Пример создания собственного конфига:

    @register_schema("MyManagerConfig")
    class MyManagerConfig(ChannelRoutingConfig):
        manager_name: str = "MyManager"
        buffer_type: str = "batch"
        batch_size: int = 50

    cfg = MyManagerConfig(channels={"console": {"type": "console"}})
    name, d = cfg.build()
    # name == "MyManager"
    # d == {"manager_name": "MyManager", "buffer_type": "batch", ...}
"""
from typing import Annotated, Dict, Any

from ...data_schema_module import (
    SchemaBase,
    FieldMeta,
    register_schema,
)


@register_schema("ChannelRoutingConfig")
class ChannelRoutingConfig(SchemaBase):
    """Базовый конфиг для ChannelRoutingManager и всех наследников.

    Общие поля:
        manager_name — имя менеджера
        channels     — описание каналов (Dict at Boundary: channel_name → channel_params)

    Каждый наследник добавляет свои поля и, при необходимости,
    переопределяет build() для кастомной сборки dict.
    """

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "ChannelRoutingManager"

    channels: Annotated[
        Dict[str, dict],
        FieldMeta("Каналы: {name: {type, enabled, ...}}")
    ] = {}

    def build(self) -> tuple[str, dict]:
        """Вернуть (manager_name, config_dict) для normalize_config().

        Подклассы могут переопределить для кастомной сборки
        (например, ErrorManagerConfig строит channels из severity-путей).
        """
        return (self.manager_name, self.model_dump())
