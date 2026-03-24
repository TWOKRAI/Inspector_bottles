# -*- coding: utf-8 -*-
"""
ProcessDataContainer — обёртка над ProcessData.custom['component_dnas'].

Зависит от process_module.ProcessData — поэтому в extensions/.
Не импортируется автоматически в основном __init__.py.

Использование:
    from data_schema_module.extensions.process_data_container import ProcessDataContainer
"""
from ..storage.process_data_container import ProcessDataContainer

__all__ = ["ProcessDataContainer"]
