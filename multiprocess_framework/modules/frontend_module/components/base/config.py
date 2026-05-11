# -*- coding: utf-8 -*-
"""
Базовые схемы конфигурации — BaseControlConfig, BindingConfig, LabelOverride, merge_config.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Optional, TypeVar

T = TypeVar("T")


@dataclass
class BaseControlConfig:
    """Общие настройки для любого контрола.

    Поля прав доступа (PR3 auth-rbac):
    - `access_level`             — legacy fallback (числовой уровень).
    - `required_view_permission` — имя permission для просмотра поля; если
      `AccessContext.has_permission(name)` == False, контрол скрывается
      (`setVisible(False)`).
    - `required_edit_permission` — имя permission для редактирования; если
      контрол виден, но permission отсутствует, переходит в
      `setEnabled(False)` + Qt-свойство `readOnly=true` (стиль из QSS).

    Coherence: edit ⇒ view. Без view контрол скрыт и edit-проверка не
    выполняется.
    """

    label: Optional[str] = None
    tooltip: Optional[str] = None
    enabled: bool = True
    access_level: int = 0
    required_view_permission: Optional[str] = None
    required_edit_permission: Optional[str] = None


@dataclass
class BindingConfig:
    """
    Привязка контрола к полю регистра.

    Структурно удовлетворяет `IFieldBinding`; `to_config_dict()` нужен для `SchemaTrait`
    (без него trait подставит пустой dict к `ResolvedMeta.merge`).
    """

    register_name: str
    field_name: str
    access_level: int = 0
    index: Optional[int] = None  # для элементов массива (например, color_lower[0])

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


@dataclass
class LabelOverride:
    """Переопределение метки и опционально transfer_k, round_k, min, max."""

    label: Optional[str] = None
    transfer_k: Optional[float] = None
    round_k: Optional[int] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None

    def to_merge_dict(self) -> dict:
        """Dict для ResolvedMeta.merge (только не-None ключи)."""
        d: dict = {}
        if self.label is not None:
            d["label"] = self.label
        if self.transfer_k is not None:
            d["transfer_k"] = self.transfer_k
        if self.round_k is not None:
            d["round_k"] = self.round_k
        if self.min_val is not None:
            d["min"] = self.min_val
        if self.max_val is not None:
            d["max"] = self.max_val
        return d


def merge_config(default: T, override: T | None) -> T:
    """
    Слить default с override. Поля из override, которые не None, замещают default.

    Использует dataclasses.replace. Оба аргумента должны быть одного типа.
    """
    if override is None:
        return default
    if type(default) is not type(override):
        raise TypeError(
            f"merge_config: default и override должны быть одного типа, "
            f"получены {type(default).__name__} и {type(override).__name__}"
        )
    merged = {}
    for f in fields(default):
        name = f.name
        override_val = getattr(override, name, None)
        if override_val is not None:
            merged[name] = override_val
        else:
            merged[name] = getattr(default, name)
    return replace(default, **merged)
