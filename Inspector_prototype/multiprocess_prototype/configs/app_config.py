# multiprocess_prototype\configs\app_config.py
"""
Конфигурация приложения Inspector Prototype.

Централизованные пути для логов, ошибок и сообщений.
Метрики → StatsManager, логи → LoggerManager, ошибки → ErrorManager.
Сообщения дублируются в LoggerManager (messages.log) для отладки.
"""

from typing import Dict, Any
import os


def get_log_dir() -> str:
    """Путь к каталогу логов. Можно переопределить через INSPECTOR_LOG_DIR."""
    return os.environ.get("INSPECTOR_LOG_DIR", "logs")


def get_default_managers_config(log_dir: str | None = None) -> Dict[str, Any]:
    """
    Конфигурация менеджеров для всех процессов.

    Возвращает:
        - logger: system.log, messages.log, console (INSPECTOR_LOG_LEVEL для уровня)
        - error: errors.log
        - stats: метрики
        - router: duplicate_messages_to_logger для отладки

    Args:
        log_dir: Каталог для логов. По умолчанию — get_log_dir().
    """
    base = log_dir or get_log_dir()
    os.makedirs(base, exist_ok=True)

    log_level = os.environ.get("INSPECTOR_LOG_LEVEL", "INFO").upper()

    return {
        "logger": {
            "app_name": "inspector",
            "default_level": log_level,
            "enable_batching": True,
            "batch_size": 100,
            "batch_interval": 1.0,
            "channels": {
                "system_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": os.path.join(base, "system.log"),
                    "max_size": 10 * 1024 * 1024,
                    "backup_count": 5,
                    "format": "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s",
                },
                "messages_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": os.path.join(base, "messages.log"),
                    "max_size": 10 * 1024 * 1024,
                    "backup_count": 5,
                    "format": "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s",
                },
                "console": {
                    "type": "console",
                    "enabled": True,
                    "format": "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s",
                },
            },
            "scopes": {
                "SYSTEM": {
                    "enabled": True,
                    "min_level": "WARNING",
                    "channels": ["console", "system_file"],
                },
                "BUSINESS": {
                    "enabled": True,
                    "min_level": log_level,
                    "channels": ["system_file", "messages_file"],
                },
                "PERFORMANCE": {
                    "enabled": True,
                    "min_level": "INFO",
                    "channels": ["system_file"],
                },
                "DEBUG": {
                    "enabled": True,
                    "min_level": "DEBUG",
                    "channels": ["system_file"],
                },
            },
            "modules": {
                "router_messages": {
                    "enabled": True,
                    "file_path": os.path.join(base, "messages.log"),
                    "min_level": "DEBUG",
                },
            },
        },
        "error": {
            "error_file_path": os.path.join(base, "errors.log"),
            "critical_file_path": os.path.join(base, "critical.log"),
            "warnings_file_path": os.path.join(base, "warnings.log"),
            "include_stacktrace": True,
        },
        "stats": {
            "enable_logging": True,
        },
        "router": {
            "duplicate_messages_to_logger": True,
        },
    }
