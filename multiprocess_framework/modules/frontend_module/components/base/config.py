# -*- coding: utf-8 -*-
"""
Базовые схемы конфигурации — BaseControlConfig, BindingConfig, merge_config.

Все конфиги компонентов наследуют SchemaBase (Pydantic v2 + FieldMeta).
LabelOverride убран — его роль выполняет model_dump(exclude_none=True).
"""

from __future__ import annotations

from typing import Annotated, Any, Optional, TypeVar

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

T = TypeVar("T")


class BaseControlConfig(SchemaBase):
    """Общие настройки для любого контрола.

    Поля прав доступа (PR3 auth-rbac):
    - ``access_level``             — legacy fallback (числовой уровень).
    - ``required_view_permission`` — имя permission для просмотра поля; если
      ``AccessContext.has_permission(name)`` == False, контрол скрывается.
    - ``required_edit_permission`` — имя permission для редактирования; если
      контрол виден, но permission отсутствует, ``setEnabled(False)``.
    """

    label: Annotated[Optional[str], FieldMeta("Текст метки")] = None
    tooltip: Annotated[Optional[str], FieldMeta("Подсказка")] = None
    enabled: Annotated[bool, FieldMeta("Доступен для редактирования")] = True
    access_level: Annotated[int, FieldMeta("Уровень доступа", min=0)] = 0
    required_view_permission: Optional[str] = None
    required_edit_permission: Optional[str] = None

    def to_override_dict(self) -> dict:
        """Dict для слияния с ResolvedMeta (только не-None ключи).

        Замена старого ``LabelOverride.to_merge_dict()``.
        Подклассы с дополнительными полями (min_val, max_val)
        переопределяют этот метод.
        """
        d: dict = {}
        if self.label is not None:
            d["label"] = self.label
        return d


class BindingConfig(SchemaBase):
    """
    Привязка контрола к полю регистра.

    Структурно удовлетворяет ``IFieldBinding``; ``to_config_dict()`` нужен
    для ``SchemaTrait``.

    Поддерживает позиционные аргументы: ``BindingConfig("reg", "field")``.
    """

    register_name: Annotated[str, FieldMeta("Имя регистра")]
    field_name: Annotated[str, FieldMeta("Имя поля")]
    access_level: Annotated[int, FieldMeta("Уровень доступа", min=0)] = 0
    index: Annotated[Optional[int], FieldMeta("Индекс элемента массива")] = None

    def __init__(
        self,
        register_name: str | None = None,
        field_name: str | None = None,
        /,
        **kwargs: Any,
    ) -> None:
        """Позиционные аргументы для обратной совместимости с dataclass-API."""
        if register_name is not None:
            kwargs.setdefault("register_name", register_name)
        if field_name is not None:
            kwargs.setdefault("field_name", field_name)
        super().__init__(**kwargs)

    def to_config_dict(self) -> dict:
        """Dict для ResolvedMeta.merge и совместимости с model_dump."""
        d = {
            "register_name": self.register_name,
            "field_name": self.field_name,
            "access_level": self.access_level,
        }
        if self.index is not None:
            d["index"] = self.index
        return d


def merge_config(default: T, override: T | None) -> T:
    """
    Слить default с override. Поля из override, которые не None, замещают default.

    Поддерживает SchemaBase (Pydantic v2): использует model_dump/model_validate.
    Оба аргумента должны быть одного типа.
    """
    if override is None:
        return default
    if type(default) is not type(override):
        raise TypeError(
            f"merge_config: default и override должны быть одного типа, "
            f"получены {type(default).__name__} и {type(override).__name__}"
        )
    cls = type(default)
    default_data = default.model_dump()
    override_data = override.model_dump(exclude_unset=True)
    default_data.update(override_data)
    return cls.model_validate(default_data)
