"""
Интеграционные тесты и шаблонное приложение для Multiprocess Framework.

Этот модуль содержит:
- Шаблонное приложение (template_app) - полноценный пример использования фреймворка
- Интеграционные тесты - тесты взаимодействия всех модулей
- Документацию - руководства по использованию шаблона

Использование:
    from multiprocess_framework.refactored.tests.integration.template_app import (
        TemplateApplication,
        AppConfigManager,
        AppConfig
    )
    
    # Создаем приложение
    config = AppConfigManager().load_config()
    app = TemplateApplication(config=config)
    app.initialize()
    app.start()
    # ...
    app.stop()
"""

from .template_app import TemplateApplication, AppConfigManager, AppConfig

__all__ = [
    'TemplateApplication',
    'AppConfigManager',
    'AppConfig'
]
