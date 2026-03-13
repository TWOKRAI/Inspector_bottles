# -*- coding: utf-8 -*-
"""
Модели компонентов фреймворка.

Не импортируются автоматически в основном __init__.py.
Зависят от pydantic и специфичны для фреймворка.

Использование:
    from data_schema_module.extensions.models import BaseComponentModel, BaseManagerModel
    from data_schema_module.extensions.models import ComponentDNA, ComponentType
"""
from ...models.base import BaseComponentModel, BaseManagerModel
from ...models.types import ComponentType

__all__ = [
    "BaseComponentModel",
    "BaseManagerModel",
    "ComponentType",
]

# ComponentDNA опциональный (может отсутствовать)
try:
    from ...models.dna import (
        ComponentDNA,
        ResourceReference,
        ResourceType,
        ComponentLocation,
        ComponentHierarchy,
    )
    __all__ += ["ComponentDNA", "ResourceReference", "ResourceType", "ComponentLocation", "ComponentHierarchy"]
except ImportError:
    pass
