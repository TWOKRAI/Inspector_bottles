"""Конфиг DatabasePlugin — параметры подключения и буферизации."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("DatabasePluginConfigV1")
class DatabasePluginConfig(PluginConfig):
    """Конфиг плагина базы данных.

    Output-плагин: принимает detection_result → буферизует → batch insert.
    Использует configure_managers() для раннего создания SQLManager.
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.database.sqlite_storage.plugin.DatabasePlugin"
    )
    plugin_name: str = "database"
    category: str = "output"

    # Подключение
    db_url: str = "sqlite:///./data/db/inspector.db"
    db_dialect: str = "sqlite"

    # Буферизация
    batch_size: int = 50
    flush_interval_sec: float = 1.0

    # Схема данных
    schema_module_path: str = "multiprocess_prototype.services.database.schema"
    schema_class_name: str = "DetectionSchema"
