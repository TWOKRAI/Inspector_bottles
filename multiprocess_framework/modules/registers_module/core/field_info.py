# -*- coding: utf-8 -*-
"""FieldInfo — описание одного поля регистра для GUI.

Извлекает метаданные из Pydantic model_fields + FieldMeta.
Используется RegistersManager.get_fields() и прикладными GUI-фабриками.

``to_dict()``/``from_dict()`` (Task 1b.2a) — dict-кодек для передачи FieldInfo через
IPC-границу (Dict at Boundary, Правило 1 CLAUDE.md): хаб отдаёт форму регистра GUI-
процессу без импорта класса плагина. Закрытый набор тегов типа зеркалит
``multiprocess_prototype/frontend/forms/factory/kinds.py::_resolve_kind`` (без
``FieldMeta.widget``-override — это чисто про Python-тип поля, framework НЕ
импортирует prototype, Правило 9 CLAUDE.md).
"""

from __future__ import annotations

import json
import types as _types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional, get_args, get_origin

from ...data_schema_module import FieldMeta

_UNION_REPRS = ("typing.Union", "<class 'types.UnionType'>")


def _unwrap_optional(field_type: Any) -> tuple[Any, bool]:
    """Снять Optional[X] -> (X, True). Иначе -> (field_type, False)."""
    origin = get_origin(field_type)
    if origin is _types.UnionType or (origin is not None and repr(origin) in _UNION_REPRS):
        non_none = [a for a in get_args(field_type) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0], True
    return field_type, False


def _type_tag(t: Any) -> str:
    """Определить закрытый тег типа поля (без Optional — снят заранее).

    Порядок проверок зеркалит ``kinds.py::_resolve_kind`` (без FieldMeta.widget):
    bool раньше int (bool — подкласс int), Literal, tuple[int,int,int], int,
    float, str, path, list/dict (в т.ч. параметризованные), иначе unsupported.
    """
    if t is bool:
        return "bool"
    if get_origin(t) is Literal:
        return "literal"
    origin = get_origin(t)
    if origin is tuple and get_args(t) == (int, int, int):
        return "tuple3int"
    if t is int:
        return "int"
    if t is float:
        return "float"
    if t is str:
        return "str"
    if t is Path:
        return "path"
    if t is dict or origin is dict:
        return "dict"
    if t is list or origin is list:
        return "list"
    return "unsupported"


def _safe_default(value: Any) -> Any:
    """default -> JSON-safe значение (никогда не бросает)."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


@dataclass(frozen=True)
class FieldInfo:
    """Описание одного поля регистра для GUI-генерации."""

    plugin_name: str
    field_name: str
    field_type: type
    default: Any
    meta: FieldMeta | None = None
    category: str = ""

    @property
    def title(self) -> str:
        """Человекочитаемое название поля."""
        if self.meta and self.meta.description:
            return self.meta.description
        return self.field_name

    @property
    def min_value(self) -> float | int | None:
        """Минимальное значение из FieldMeta."""
        return self.meta.min if self.meta else None

    @property
    def max_value(self) -> float | int | None:
        """Максимальное значение из FieldMeta."""
        return self.meta.max if self.meta else None

    @property
    def unit(self) -> str:
        """Единица измерения."""
        return getattr(self.meta, "unit", "") or "" if self.meta else ""

    @property
    def ui_group(self) -> str | None:
        """Группа для визуальной компоновки формы (build_form_for_schema)."""
        return self.meta.ui_group if self.meta else None

    @property
    def ui_order(self) -> int | None:
        """Порядок поля внутри формы (build_form_for_schema)."""
        return self.meta.ui_order if self.meta else None

    @property
    def ui_hidden(self) -> bool:
        """True — поле не должно показываться в сгенерированной форме."""
        return bool(self.meta.ui_hidden) if self.meta else False

    @property
    def ui_widget(self) -> str:
        """Widget-hint для резолвера kinds — алиас FieldMeta.widget (единый источник)."""
        return getattr(self.meta, "widget", "") or "" if self.meta else ""

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict для IPC-границы (Task 1b.2a).

        ``choices`` добавляется ТОЛЬКО когда ``type == "literal"`` (закрытый тег-набор
        см. модульный docstring). Default всегда JSON-safe (``_safe_default``) —
        Path/tuple конвертируются, неизвестные типы падают в ``str(default)``.
        """
        unwrapped, optional = _unwrap_optional(self.field_type)
        tag = _type_tag(unwrapped)
        d: dict[str, Any] = {
            "plugin_name": self.plugin_name,
            "field_name": self.field_name,
            "type": tag,
            "optional": optional,
            "default": _safe_default(self.default),
            "meta": self.meta.to_dict() if self.meta is not None else None,
            "category": self.category,
        }
        if tag == "literal":
            d["choices"] = list(get_args(unwrapped))
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FieldInfo":
        """Восстановить FieldInfo из ``to_dict()`` — reconstructs Python type по тегу.

        ``unsupported`` восстанавливается как ``object`` (сам по себе классифицируется
        обратно в ``unsupported`` — round-trip тега стабилен, даже если исходный
        Python-тип не переносится через границу).
        """
        tag = d["type"]
        optional = bool(d.get("optional", False))
        default = d.get("default")

        field_type: Any
        if tag == "literal":
            choices = tuple(d.get("choices") or [])
            field_type = Literal[choices] if choices else Literal[None]
        elif tag == "tuple3int":
            field_type = tuple[int, int, int]
            if isinstance(default, list):
                default = tuple(default)
        elif tag == "path":
            field_type = Path
            if isinstance(default, str):
                default = Path(default)
        elif tag == "bool":
            field_type = bool
        elif tag == "int":
            field_type = int
        elif tag == "float":
            field_type = float
        elif tag == "str":
            field_type = str
        elif tag == "list":
            field_type = list
        elif tag == "dict":
            field_type = dict
        else:
            field_type = object

        if optional:
            field_type = Optional[field_type]

        meta_dict = d.get("meta")
        meta = FieldMeta.from_dict(meta_dict) if meta_dict is not None else None

        return cls(
            plugin_name=d["plugin_name"],
            field_name=d["field_name"],
            field_type=field_type,
            default=default,
            meta=meta,
            category=d.get("category", ""),
        )


def extract_fields(plugin_name: str, register_cls: type, category: str = "") -> list[FieldInfo]:
    """Извлечь FieldInfo из register-класса (Pydantic model).

    Args:
        plugin_name: Имя плагина-владельца.
        register_cls: SchemaBase-класс регистра.
        category: Категория плагина (source/processing/output).

    Returns:
        Список FieldInfo для всех полей модели.
    """
    result: list[FieldInfo] = []

    for name, field_info in register_cls.model_fields.items():
        # Извлечь FieldMeta из Annotated metadata
        meta = None
        for m in field_info.metadata:
            if isinstance(m, FieldMeta):
                meta = m
                break

        result.append(
            FieldInfo(
                plugin_name=plugin_name,
                field_name=name,
                field_type=field_info.annotation or type(None),
                default=field_info.default,
                meta=meta,
                category=category,
            )
        )

    return result
