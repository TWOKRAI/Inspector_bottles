# -*- coding: utf-8 -*-
"""Нормализация dict / None в экземпляры SchemaBase для виджетов с Pydantic-конфигом."""
from __future__ import annotations

from typing import Any, Dict, Optional, Type, TypeVar, Union

from multiprocess_framework.modules.data_schema_module import SchemaBase

T = TypeVar("T", bound=SchemaBase)


def coerce_schema_config(
    config: Optional[Union[T, Dict[str, Any]]],
    model: Type[T],
) -> T:
    """None → пустая модель; уже модель → как есть; dict → model_validate."""
    if config is None:
        return model()
    if isinstance(config, model):
        return config
    return model.model_validate(config)
