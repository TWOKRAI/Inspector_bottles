"""
Обработчик конфигурации процесса.
"""

from .managers_normalize import MANAGER_SECTION_KEYS, normalize_managers_view
from .process_config_handler import ProcessConfigHandler
from .process_launch_config import ProcessLaunchConfig

__all__ = [
    "MANAGER_SECTION_KEYS",
    "normalize_managers_view",
    "ProcessConfigHandler",
    "ProcessLaunchConfig",
]
