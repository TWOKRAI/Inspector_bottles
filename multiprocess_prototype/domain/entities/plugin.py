# -*- coding: utf-8 -*-
"""
PluginInstance — entity для одного плагина внутри Process.

Хранит имя плагина и его конфигурацию в виде нетипизированного dict.
Типизация config через PluginCatalog.resolve(name).config_schema будет
добавлена в Phase C как opt-in валидация.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, model_validator
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

    @model_validator(mode="before")
    @classmethod
    def _fold_extra_into_config(cls, data: Any) -> Any:
        """Свернуть плоские runtime-поля плагина в ``config``.

        Runnable-топологии (backend/topology) задают параметры плагина плоско
        (``camera_id``, ``fps``, ``regions`` …). Domain-модель хранит их в
        ``config`` (passthrough). Сворачиваем без потери данных, чтобы редактор
        мог открывать любой runnable-pipeline. Явный ``config`` имеет приоритет.
        """
        if not isinstance(data, dict):
            return data
        known = {"plugin_name", "plugin_class", "category", "config"}
        extras = {k: v for k, v in data.items() if k not in known}
        if not extras:
            return data
        result = {k: v for k, v in data.items() if k in known}
        config = dict(result.get("config") or {})
        for key, value in extras.items():
            config.setdefault(key, value)
        result["config"] = config
        return result

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
