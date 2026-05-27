# -*- coding: utf-8 -*-
"""
PluginInstance — entity для одного плагина внутри Process.

Хранит имя плагина и его конфигурацию в виде нетипизированного dict.
Типизация config через PluginCatalog.resolve(name).config_schema будет
добавлена в Phase C как opt-in валидация.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase


class PluginInstance(SchemaBase):
    """Описывает один экземпляр плагина внутри Process."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
        # validate_assignment теряет смысл при frozen=True
    )

    plugin_name: Annotated[str, FieldMeta("Идентификатор плагина (plugin_name из реестра)")]
    plugin_class: Annotated[
        str | None,
        FieldMeta("Полный путь класса плагина (используется runtime-лоадером)"),
    ] = None
    category: Annotated[
        str | None,
        FieldMeta("Категория плагина (из реестра)"),
    ] = None
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Конфигурация плагина. Нетипизированный dict в Phase B.",
    )

    # ------------------------------------------------------------------
    # Сериализация (тонкие обёртки для читаемости в presenter-ах)
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать PluginInstance из словаря."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (mode='json': tuple→list, datetime→str)."""
        return self.model_dump(mode="json")
