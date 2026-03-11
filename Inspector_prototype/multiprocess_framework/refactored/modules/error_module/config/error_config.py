"""
ErrorManagerConfig — RegisterBase-конфиг для ErrorManager.

По образцу process_1_config: data_schema_module как точка истины.
build() возвращает (manager_name, config_dict) — dict совместим с LogConfig.from_dict().
"""

from typing import Annotated

from ...data_schema_module import (
    RegisterBase,
    FieldMeta,
    register_schema,
)


@register_schema("ErrorManagerConfig")
class ErrorManagerConfig(RegisterBase):
    """Регистр конфигурации ErrorManager."""

    manager_name: str = "ErrorManager"
    app_name: str = "errors"
    error_file_path: Annotated[str, FieldMeta("Путь к файлу ошибок")] = "logs/errors.log"
    default_level: Annotated[str, FieldMeta("Минимальный уровень")] = "ERROR"
    include_stacktrace: bool = True
    enable_batching: Annotated[bool, FieldMeta("Батчинг")] = True
    batch_size: Annotated[int, FieldMeta("Размер батча", min=1, max=1000)] = 50
    batch_interval: Annotated[float, FieldMeta("Интервал flush (сек)", min=0.1, max=60.0)] = 0.5

    def build(self) -> tuple[str, dict]:
        """
        Вернуть (manager_name, config_dict) для ErrorManager.

        config_dict совместим с LogConfig.from_dict().
        include_stacktrace — доп. поле для ErrorManager.
        """
        return (self.manager_name, {
            "app_name": self.app_name,
            "default_level": self.default_level,
            "include_stacktrace": self.include_stacktrace,
            "enable_batching": self.enable_batching,
            "batch_size": self.batch_size,
            "batch_interval": self.batch_interval,
            "channels": {
                "errors_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": self.error_file_path,
                    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    "max_size": 10 * 1024 * 1024,
                    "backup_count": 5,
                },
            },
        })
