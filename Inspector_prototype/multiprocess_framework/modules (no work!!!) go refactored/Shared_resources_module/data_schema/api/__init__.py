"""
API для работы с данными менеджеров.

Содержит ManagerDataAdapter и упрощенный API.
"""

from .manager_adapter import ManagerDataAdapter
from .simple_api import (
    create_config,
    create_manager_config,
    get_config,
    config_from_dict,
    auto_config,
)

__all__ = [
    'ManagerDataAdapter',
    'create_config',
    'create_manager_config',
    'get_config',
    'config_from_dict',
    'auto_config',
]


