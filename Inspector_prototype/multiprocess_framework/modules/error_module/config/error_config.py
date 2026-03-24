# -*- coding: utf-8 -*-
"""
ErrorManagerConfig — RegisterBase-конфиг для ErrorManager.

Наследует ChannelRoutingConfig — участвует в едином конфиг-дереве фреймворка.

Три severity-канала строятся из file_path атрибутов в build().
Унаследованное поле `channels: Dict[str, dict]` служит точкой расширения:
любые дополнительные каналы (например, Telegram, Slack) добавляются туда
и автоматически включаются в итоговый config_dict.

Пример:
    # Минимальный конфиг:
    config = ErrorManagerConfig()
    em = ErrorManager(config=config)

    # С кастомным файлом и severity-overrides:
    config = ErrorManagerConfig(
        error_file_path="var/log/errors.log",
        critical_file_path="var/log/critical.log",
        include_stacktrace=True,
    )

    # Добавить Telegram-канал через наследованное поле:
    config = ErrorManagerConfig(
        channels={"telegram": {"type": "http", "url": "https://..."}}
    )
"""

from typing import Annotated, Dict, Optional

from ...data_schema_module import FieldMeta, register_schema
from ...channel_routing_module import ChannelRoutingConfig


@register_schema("ErrorManagerConfig")
class ErrorManagerConfig(ChannelRoutingConfig):
    """Конфигурация ErrorManager с severity-based channel routing.

    Наследует ChannelRoutingConfig:
      manager_name: str = "ErrorManager"
      channels: Dict[str, dict] = {}   ← дополнительные каналы (расширение)

    Severity-каналы строятся автоматически из file_path полей в build().
    """

    manager_name: str = "ErrorManager"
    app_name: str = "errors"

    critical_file_path: Annotated[str, FieldMeta("Путь к файлу критических ошибок")] = "logs/critical.log"
    error_file_path: Annotated[str, FieldMeta("Путь к файлу ошибок")] = "logs/errors.log"
    warnings_file_path: Annotated[
        Optional[str], FieldMeta("Путь к файлу предупреждений (None — не создавать)")
    ] = "logs/warnings.log"

    default_level: Annotated[str, FieldMeta("Минимальный уровень логирования")] = "WARNING"
    include_stacktrace: bool = True
    enable_batching: Annotated[bool, FieldMeta("Батчинг")] = True
    batch_size: Annotated[int, FieldMeta("Размер батча", min=1, max=1000)] = 50
    batch_interval: Annotated[float, FieldMeta("Интервал flush (сек)", min=0.1, max=60.0)] = 0.5

    def build(self) -> tuple[str, dict]:
        """Вернуть (manager_name, config_dict) для ErrorManager.

        Строит severity-каналы из file_path атрибутов, затем мержит с
        дополнительными каналами из унаследованного ChannelRoutingConfig.channels.
        """
        severity_channels: Dict[str, dict] = {
            "critical_file": {
                "type": "file",
                "enabled": True,
                "file_path": self.critical_file_path,
                "format": "%(asctime)s [CRITICAL] %(name)s: %(message)s",
                "max_size": 10 * 1024 * 1024,
                "backup_count": 10,
            },
            "errors_file": {
                "type": "file",
                "enabled": True,
                "file_path": self.error_file_path,
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "max_size": 10 * 1024 * 1024,
                "backup_count": 5,
            },
        }

        if self.warnings_file_path:
            severity_channels["warnings_file"] = {
                "type": "file",
                "enabled": True,
                "file_path": self.warnings_file_path,
                "format": "%(asctime)s [WARNING] %(name)s: %(message)s",
                "max_size": 5 * 1024 * 1024,
                "backup_count": 3,
            }

        all_channels = {**severity_channels, **self.channels}

        return (self.manager_name, {
            "app_name": self.app_name,
            "default_level": self.default_level,
            "include_stacktrace": self.include_stacktrace,
            "enable_batching": self.enable_batching,
            "batch_size": self.batch_size,
            "batch_interval": self.batch_interval,
            "channels": all_channels,
        })
