# -*- coding: utf-8 -*-
"""
ErrorManagerConfig — RegisterBase-конфиг для ErrorManager.

По образцу process_1_config: data_schema_module как точка истины.
build() возвращает (manager_name, config_dict) — dict совместим с LogConfig.from_dict().

Три severity-канала (по умолчанию):
  critical_file_path → logs/critical.log  (CRITICAL)
  error_file_path    → logs/errors.log    (ERROR)
  warnings_file_path → logs/warnings.log  (WARNING, None = не создавать)
"""

from typing import Annotated, Optional

from ...data_schema_module import (
    RegisterBase,
    FieldMeta,
    register_schema,
)


@register_schema("ErrorManagerConfig")
class ErrorManagerConfig(RegisterBase):
    """Конфигурация ErrorManager с severity-based channel routing.

    Пример:
        config = ErrorManagerConfig(
            error_file_path="var/log/errors.log",
            critical_file_path="var/log/critical.log",
            include_stacktrace=True,
        )
        em = ErrorManager(config=config)
    """

    manager_name: str = "ErrorManager"
    app_name: str = "errors"

    # Severity channels
    critical_file_path: Annotated[str, FieldMeta("Путь к файлу критических ошибок")] = "logs/critical.log"
    error_file_path: Annotated[str, FieldMeta("Путь к файлу ошибок")] = "logs/errors.log"
    warnings_file_path: Annotated[Optional[str], FieldMeta("Путь к файлу предупреждений (None — не создавать)")] = "logs/warnings.log"

    # Уровень и батчинг
    default_level: Annotated[str, FieldMeta("Минимальный уровень логирования")] = "WARNING"
    include_stacktrace: bool = True
    enable_batching: Annotated[bool, FieldMeta("Батчинг")] = True
    batch_size: Annotated[int, FieldMeta("Размер батча", min=1, max=1000)] = 50
    batch_interval: Annotated[float, FieldMeta("Интервал flush (сек)", min=0.1, max=60.0)] = 0.5

    def build(self) -> tuple[str, dict]:
        """Вернуть (manager_name, config_dict) для ErrorManager.

        config_dict совместим с LogConfig.from_dict() + include_stacktrace.
        Каналы строятся по severity: critical_file, errors_file, warnings_file.
        """
        channels: dict = {}

        channels["critical_file"] = {
            "type": "file",
            "enabled": True,
            "file_path": self.critical_file_path,
            "format": "%(asctime)s [CRITICAL] %(name)s: %(message)s",
            "max_size": 10 * 1024 * 1024,
            "backup_count": 10,
        }

        channels["errors_file"] = {
            "type": "file",
            "enabled": True,
            "file_path": self.error_file_path,
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "max_size": 10 * 1024 * 1024,
            "backup_count": 5,
        }

        if self.warnings_file_path:
            channels["warnings_file"] = {
                "type": "file",
                "enabled": True,
                "file_path": self.warnings_file_path,
                "format": "%(asctime)s [WARNING] %(name)s: %(message)s",
                "max_size": 5 * 1024 * 1024,
                "backup_count": 3,
            }

        return (self.manager_name, {
            "app_name": self.app_name,
            "default_level": self.default_level,
            "include_stacktrace": self.include_stacktrace,
            "enable_batching": self.enable_batching,
            "batch_size": self.batch_size,
            "batch_interval": self.batch_interval,
            "channels": channels,
        })
