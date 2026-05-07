"""Конфиг DatabasePlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

from .registers import DatabaseRegisters


@register_schema("DatabasePluginConfigV1")
class DatabasePluginConfig(PluginConfig):
    """Конфиг плагина записи результатов в SQLite — identity + register binding.

    Все параметры (db_path, batch_size, flush_interval_sec) — в DatabaseRegisters.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.database.plugin.DatabasePlugin"
    )
    plugin_name: str = "database"
    category: str = "output"

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [DatabaseRegisters]
