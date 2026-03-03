"""Базовые Pydantic модели для компонентов системы."""

from .base import BaseComponentModel, BaseManagerModel
from .types import ComponentType

# Расширенная ДНК (опционально)
try:
    from .dna import (
        ComponentDNA,
        ComponentLocation,
        ResourceReference,
        ResourceType,
        ComponentHierarchy
    )
    __all__ = [
        'BaseComponentModel',
        'BaseManagerModel',
        'ComponentType',
        'ComponentDNA',
        'ComponentLocation',
        'ResourceReference',
        'ResourceType',
        'ComponentHierarchy',
    ]
except ImportError:
    __all__ = [
        'BaseComponentModel',
        'BaseManagerModel',
        'ComponentType',
    ]

