# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

RegistersContainer перемещён в container/registers_container.py.

Используйте новый путь:
    from data_schema_module.container import RegistersContainer
    from data_schema_module import RegistersContainer
"""
from ..container.registers_container import RegistersContainer

__all__ = ["RegistersContainer"]
