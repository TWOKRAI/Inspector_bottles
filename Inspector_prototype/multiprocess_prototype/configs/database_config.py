# multiprocess_prototype\configs\database_config.py
"""
Конфигурация DatabaseProcess (опционально).

Использование: раскомментировать в main.py для добавления процесса с БД.
"""
from multiprocess_framework.refactored.modules.data_schema_module import register_schema
from multiprocess_framework.refactored.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.processes.database_process import DatabaseProcess


@register_schema("DatabaseConfig")
class DatabaseConfig(ProcessConfigBase):
    """Конфигурация процесса с SQLManager."""

    process_name: str = "database"
    class_path: str = class_path_from_type(DatabaseProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.NORMAL
    db_url: str = "sqlite:///./inspector.db"
    db_dialect: str = "sqlite"
