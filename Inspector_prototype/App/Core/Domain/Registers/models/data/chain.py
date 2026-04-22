# -*- coding: utf-8 -*-
"""
ChainStepData — шаг цепочки обработки региона.
"""
from typing import Any, Dict

from pydantic import BaseModel, Field


class ChainStepData(BaseModel):
    """Один шаг в цепочке обработки региона."""

    # Идентификатор процессора (имя алгоритма)
    processor_id: str = ""

    # Параметры процессора (произвольный словарь)
    params: Dict[str, Any] = Field(default_factory=dict)

    # Флаг активности шага
    enabled: bool = True
