# -*- coding: utf-8 -*-
"""
Фабрики моделей и ДНК компонентов.

Не импортируются автоматически в основном __init__.py.

Использование:
    from data_schema_module.extensions.factory import ModelFactory
"""
from ...factory.model_factory import ModelFactory

__all__ = ["ModelFactory"]

try:
    from ...factory.dna_factory import DNAFactory
    __all__ += ["DNAFactory"]
except ImportError:
    pass
