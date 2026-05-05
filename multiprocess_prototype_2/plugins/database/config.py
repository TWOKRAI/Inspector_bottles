"""Конфиг DatabasePlugin."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("DatabasePluginConfigV1")
class DatabasePluginConfig(PluginConfig):
    """Конфиг плагина записи результатов в SQLite.

    Принимает detection_result, буферизует, batch insert.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.database.plugin.DatabasePlugin"
    )
    plugin_name: str = "database"
    category: str = "output"

    db_path: Annotated[
        str,
        FieldMeta(description="Путь к SQLite файлу"),
    ] = "data/inspector.db"

    batch_size: Annotated[
        int,
        FieldMeta(description="Размер batch для flush"),
    ] = 100

    flush_interval_sec: Annotated[
        float,
        FieldMeta(description="Интервал авто-flush (секунды)"),
    ] = 2.0
