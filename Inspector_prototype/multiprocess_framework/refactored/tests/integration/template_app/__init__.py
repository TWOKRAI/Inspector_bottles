"""
Шаблонное приложение для демонстрации использования Multiprocess Framework.

Это полноценное приложение, демонстрирующее использование всех модулей
фреймворка в реальном сценарии. Может использоваться как шаблон для
создания собственных приложений.

Демонстрирует:
- Создание процессов через ProcessManagerCore
- Использование ProcessModule для базовых процессов
- Управление потоками через WorkerManager
- Работу с конфигурациями через ConfigManager
- Работу со схемами данных через DataSchemaManager
- Межпроцессное взаимодействие через RouterManager
- Обработку команд через CommandManager
- Логирование через LoggerManager
- Использование SharedResourcesManager для общих ресурсов

Структура:
- TemplateApplication - главный класс приложения
- AppConfig - конфигурация приложения
- AppConfigManager - менеджер конфигурации
- processes/ - примеры процессов (Vision, AI, DB, UI)

Использование:
    from multiprocess_framework.refactored.tests.integration.template_app import (
        TemplateApplication,
        AppConfigManager,
        AppConfig
    )
    
    config = AppConfigManager().load_config()
    app = TemplateApplication(config=config)
    app.initialize()
    app.start()
    # ...
    app.stop()

Документация:
    См. TEMPLATE_FRAMEWORK_GUIDE.md и TEMPLATE_USAGE.md для подробного руководства
"""

from .template_application import TemplateApplication
from .config.app_config import AppConfig, AppConfigManager

__all__ = [
    'TemplateApplication',
    'AppConfig',
    'AppConfigManager'
]
