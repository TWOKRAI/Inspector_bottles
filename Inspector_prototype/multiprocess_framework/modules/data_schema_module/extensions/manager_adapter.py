# -*- coding: utf-8 -*-
"""
ManagerDataAdapter — адаптер для работы с данными менеджера через StorageManager.

Зависит от StorageManager и ProcessData — поэтому в extensions/.
Не импортируется автоматически в основном __init__.py.

Использование:
    from data_schema_module.extensions.manager_adapter import ManagerDataAdapter
"""
from ..api.manager_adapter import ManagerDataAdapter

__all__ = ["ManagerDataAdapter"]
