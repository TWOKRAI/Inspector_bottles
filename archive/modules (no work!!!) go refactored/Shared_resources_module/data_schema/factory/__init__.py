"""
Фабрика для создания моделей данных.

Единый API для создания Pydantic моделей и ДНК компонентов.
"""

from .model_factory import ModelFactory

# Опциональный импорт ДНК фабрики
try:
    from .dna_factory import DNAFactory
    _has_dna = True
except ImportError:
    _has_dna = False

__all__ = [
    'ModelFactory',
]

if _has_dna:
    __all__.append('DNAFactory')


