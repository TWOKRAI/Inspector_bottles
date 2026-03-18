# multiprocess_prototype\configs\database_config.py
"""
Конфигурация DatabaseProcess.

БД хранится в папке database/. Схема загружается из schema_module_path.
"""
from pathlib import Path

from multiprocess_framework.refactored.modules.data_schema_module import register_schema
from multiprocess_framework.refactored.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype.backend.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.backend.processes.database_process import DatabaseProcess

_db_dir = Path(__file__).resolve().parent.parent / "database"
_db_dir.mkdir(parents=True, exist_ok=True)


@register_schema("DatabaseConfig")
class DatabaseConfig(ProcessConfigBase):
    """Конфигурация процесса с SQLManager."""

    process_name: str = "database"
    class_path: str = class_path_from_type(DatabaseProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.NORMAL
    db_url: str = f"sqlite:///{_db_dir / 'inspector.db'}"
    db_dialect: str = "sqlite"
    schema_module_path: str = "multiprocess_prototype.backend.database.schema_1"
    schema_class_name: str = "DetectionSchema"
