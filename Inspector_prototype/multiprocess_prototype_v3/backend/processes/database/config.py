"""Database service configuration."""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import ProcessLaunchConfig
from pydantic import Field

_SERVICE_ROOT = Path(__file__).resolve().parent.parent.parent


@register_schema("DatabaseConfigV3")
class DatabaseConfig(ProcessLaunchConfig):
    process_name: str = "database"
    process_class: str = "multiprocess_prototype_v3.backend.processes.database.process.DatabaseProcess"
    db_url: str = Field(
        default_factory=lambda: f"sqlite:///{_SERVICE_ROOT / 'database' / 'inspector.db'}"
    )
    db_dialect: str = "sqlite"
    schema_module_path: str = "multiprocess_prototype_v3.services.database.schema"
    schema_class_name: str = "DetectionSchema"
