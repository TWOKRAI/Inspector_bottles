# -*- coding: utf-8 -*-
"""
SchemaAdapter — адаптер для интеграции process_module с data_schema_module.

Конвертирует схемы конфигурации в ProcessConfigDict (Dict at Boundary).
Не зависит от конкретной реализации data_schema_module — работает через duck typing.
"""

from typing import Any

from ..types import ProcessConfigDict


class SchemaAdapter:
    """
    Адаптер для конвертации схем конфигурации в ProcessConfigDict.

    Использование:
        adapter = SchemaAdapter()
        config_dict = adapter.adapt(schema_class)
        config_dict = adapter.adapt_instance(schema_instance)
    """

    def adapt(self, schema_class: Any) -> ProcessConfigDict:
        """
        Конвертировать класс схемы в ProcessConfigDict.

        Args:
            schema_class: Класс схемы (Pydantic, dataclass, или dict)

        Returns:
            ProcessConfigDict — конфигурация как dict
        """
        if schema_class is None:
            return {}

        # Pydantic v2
        if hasattr(schema_class, "model_fields"):
            try:
                return dict(schema_class())
            except Exception:
                pass

        # Pydantic v1 / dataclass
        if hasattr(schema_class, "__fields__") or hasattr(schema_class, "__dataclass_fields__"):
            try:
                instance = schema_class()
                return self.adapt_instance(instance)
            except Exception:
                pass

        # dict-like
        if isinstance(schema_class, dict):
            return schema_class

        return {}

    def adapt_instance(self, schema_instance: Any) -> ProcessConfigDict:
        """
        Конвертировать экземпляр схемы в ProcessConfigDict.

        Args:
            schema_instance: Экземпляр схемы

        Returns:
            ProcessConfigDict — конфигурация как dict
        """
        if schema_instance is None:
            return {}

        # Pydantic v2
        if hasattr(schema_instance, "model_dump"):
            return schema_instance.model_dump()

        # Pydantic v1
        if hasattr(schema_instance, "dict"):
            return schema_instance.dict()

        # dataclass / to_dict
        if hasattr(schema_instance, "to_dict"):
            return schema_instance.to_dict()

        # __dict__
        if hasattr(schema_instance, "__dict__"):
            return {k: v for k, v in schema_instance.__dict__.items() if not k.startswith("_")}

        # dict
        if isinstance(schema_instance, dict):
            return schema_instance

        return {}
