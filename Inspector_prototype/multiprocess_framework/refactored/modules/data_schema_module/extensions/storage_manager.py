# -*- coding: utf-8 -*-
"""
StorageManager — менеджер хранения данных компонентов в ProcessData.

Зависит от process_module.ProcessData — поэтому в extensions/.
Не импортируется автоматически в основном __init__.py.

Использование:
    from data_schema_module.extensions.storage_manager import StorageManager
"""
from ..storage.storage_manager import StorageManager

__all__ = ["StorageManager"]
