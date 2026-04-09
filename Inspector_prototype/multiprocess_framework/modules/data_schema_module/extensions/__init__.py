# -*- coding: utf-8 -*-
"""
Опциональные расширения data_schema_module.

Эти компоненты НЕ импортируются автоматически в основном __init__.py.
Они зависят от других модулей фреймворка (process_module, shared_resources_module)
и доступны только через явный импорт.

Использование:

    # StorageManager (зависит от ProcessData)
    from data_schema_module.storage.storage_manager import StorageManager

    # VersionManager (зависит от ProcessData)
    from data_schema_module.extensions.versioning import VersionManager

    # ComponentDNA (модели компонентов)
    from data_schema_module.extensions.models import ComponentDNA, BaseManagerModel

    # Инструменты визуализации
    from data_schema_module.extensions.tools import SchemaVisualizer

    # ModelFactory
    from data_schema_module.extensions.factory import ModelFactory

    # Metrics
    from data_schema_module.extensions.metrics import MetricsCollector
"""
