# -*- coding: utf-8 -*-
"""
Wire — entity для соединения между двумя узлами топологии.

Узел задаётся строкой вида «process_name», «process_name.plugin_name»
или «process_name.plugin_name.port» — семантика определяется runtime-ом.
В Phase B domain хранит только строковые идентификаторы без интерпретации.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase


class Wire(SchemaBase):
    """Типизированное соединение между двумя узлами в топологии."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    source: Annotated[str, FieldMeta("Узел-источник (process, process.plugin или process.plugin.port)")]
    target: Annotated[str, FieldMeta("Узел-приёмник")]
    src_dtype: Annotated[str | None, FieldMeta("Тип данных на выходе источника")] = None
    tgt_dtype: Annotated[str | None, FieldMeta("Тип данных на входе приёмника")] = None
    description: Annotated[str, FieldMeta("Текстовое описание соединения (для UI и документации)")] = ""

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать Wire из словаря."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return self.model_dump(mode="json")
