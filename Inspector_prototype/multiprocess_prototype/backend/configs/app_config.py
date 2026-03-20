# multiprocess_prototype\configs\app_config.py
"""
Конфигурация приложения Inspector Prototype.

Централизованные пути для логов, ошибок и сообщений.
Метрики → StatsManager, логи → LoggerManager, ошибки → ErrorManager.
Сообщения дублируются в LoggerManager (messages.log) для отладки.

Разделение логов по файлам (через config.modules):
  - database.log   — записи в БД (процесс database, module="database")
  - frames.log     — кадры (module="processor_frames")
  - processor.log  — общие логи процессора
  - messages.log   — сообщения роутера (module="router_messages")
  - system.log     — системные события
"""

from pathlib import Path
from typing import Any, Dict, Optional
import copy
import os


def merge_managers(
    base: Dict[str, Any], overlay: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Глубокий merge конфигов managers для proc_dict.

    Подклассы ProcessConfigBase могут вернуть managers_overlay() — переопределения
    сливаются поверх get_default_managers_config() (например свои logger.modules).
    """
    if not overlay:
        return copy.deepcopy(base)

    def _deep(a: dict, b: dict) -> dict:
        out = copy.deepcopy(a)
        for k, v in b.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _deep(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
        return out

    return _deep(base, overlay)

# Путь к logs по умолчанию: multiprocess_prototype/logs
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def get_log_dir() -> str:
    """Путь к каталогу логов. Можно переопределить через INSPECTOR_LOG_DIR."""
    env_path = os.environ.get("INSPECTOR_LOG_DIR")
    if env_path:
        return env_path
    return str(_DEFAULT_LOG_DIR)


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
                "database": {
                    "enabled": True,
                    "file_path": os.path.join(base, "database.log"),
                    "min_level": "INFO",
                },
                "processor": {
                    "enabled": True,
                    "file_path": os.path.join(base, "processor.log"),
                    "min_level": "INFO",
                },
                "processor_frames": {
                    "enabled": True,
                    "file_path": os.path.join(base, "frames.log"),
                    "min_level": "DEBUG",
                    # RotatingFileHandler на Windows даёт WinError 32 при rename, если файл
                    # открыт другим процессом / хвостом; perf-лог пишется часто — без ротации.
                    "rotate": False,
                },
                "camera": {
                    "enabled": True,
                    "file_path": os.path.join(base, "camera.log"),
                    "min_level": "INFO",
                },
                "renderer": {
                    "enabled": True,
                    "file_path": os.path.join(base, "renderer.log"),
                    "min_level": "INFO",
                },
                "robot": {
                    "enabled": True,
                    "file_path": os.path.join(base, "robot.log"),
                    "min_level": "INFO",
                },
                "gui": {
                    "enabled": True,
                    "file_path": os.path.join(base, "gui.log"),
                    "min_level": "INFO",
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
