"""
Модуль конфигурации для проекта.

Универсальный модуль для работы с конфигурацией во всех модулях проекта.
Поддерживает вложенные ключи, работу с файлами JSON/YAML, секции,
переменные окружения и подписку на изменения.

Основные классы:
    Config - базовый класс для работы с конфигурацией
    ConfigSection - представление секции конфигурации
    ConfigManager - менеджер для управления несколькими конфигурациями

Примеры использования:
    from ..Config_module import Config, ConfigManager
    
    # Простая работа с конфигурацией
    config = Config()
    config.set('database.host', 'localhost')
    
    # Использование менеджера (Singleton)
    config = ConfigManager.get_instance()
    config.load('config/app.yaml')
    
    # Работа с секциями
    db_config = config.section('database')
    db_config.set('host', 'localhost')
"""

from .base_config import Config, ConfigSection
from .config_manager import ConfigManager, get_config

__all__ = [
    'Config',
    'ConfigSection',
    'ConfigManager',
    'get_config',
]
