# -*- coding: utf-8 -*-
"""
Класс для создания полей Pydantic по схеме-словарю.
Схему (словарь) передаёт приложение; фреймворк только мержит её с переопределениями и возвращает Field(...).
"""
from typing import Any, Dict
from copy import deepcopy
from pydantic import Field as PydanticField


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Рекурсивно сливает overrides в base (overrides приоритетнее)."""
    result = deepcopy(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class FieldSchema:
    """
    Общий класс для создания полей по схеме-словарю.
    Схему передают в __init__; экземпляр вызываем как поле: inst(default_value, description='', **overrides).
    """

    def __init__(self, field_schema: Dict[str, Any]):
        """
        Args:
            field_schema: Базовый словарь метаданных (json_schema_extra). Переопределения задаются при вызове.
        """
        self._schema = deepcopy(field_schema)

    def __call__(
        self,
        default_value: Any,
        description: str = '',
        **overrides: Any
    ):
        """
        Создать поле Pydantic: schema + overrides -> json_schema_extra.

        Args:
            default_value: Значение по умолчанию поля.
            description: Краткое описание поля.
            **overrides: Переопределения для json_schema_extra (min, max, info, routing и т.д.).

        Returns:
            Field(...) для использования в модели Pydantic.
        """
        extra = _deep_merge(self._schema, overrides)
        return PydanticField(default=default_value, description=description, json_schema_extra=extra)

    @staticmethod
    def deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        """Рекурсивно сливает overrides в base (для общего использования)."""
        return _deep_merge(base, overrides)
