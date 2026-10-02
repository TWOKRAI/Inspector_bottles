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

try:
    from pydantic_core import PydanticUndefined as _PYDANTIC_UNDEFINED  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — pydantic всегда установлен в проекте
    _PYDANTIC_UNDEFINED = object()


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


_SCALAR_TYPES: dict[str, Any] = {
    "bool": bool,
    "int": int,
    "float": float,
    "str": str,
    "path": Path,
    "tuple3int": tuple[int, int, int],
}


def _describe_type(t: Any, *, nested: bool = False) -> dict[str, Any] | None:
    """Описать тип dict-ом ``{"type": тег, ...}`` — рекурсивно для элементов контейнеров.

    ``list[X]`` -> ``item``; ``dict[K, V]`` -> ``key``/``value`` (то же описание, что у
    верхнего уровня: ``choices`` у вложенного ``literal``, свои ``item``/``key``/``value``).
    Ключи отсутствуют у голого ``list``/``dict`` и когда тип элемента ``unsupported``
    (вне закрытого набора тегов) — копия там шире оригинала: ``Optional``/``Union``,
    ограничения через ``Annotated`` (``list[Annotated[int, Field(ge=0)]]`` с ``[-1]``:
    оригинал отвергает, копия принимает), модели, ``tuple`` кроме трёх ``int``.
    ``Any`` совпадает.
    Для ``nested=True`` ``unsupported`` и ``literal`` без вариантов -> ``None`` (ключ не
    пишется; никогда не порождаем ``Literal[None]``).
    """
    tag = _type_tag(t)
    if nested and tag == "unsupported":
        return None
    desc: dict[str, Any] = {"type": tag}
    args = get_args(t)
    if tag == "literal":
        if nested and not args:
            return None
        desc["choices"] = _json_safe(list(args))
    elif tag == "list" and args:
        item = _describe_type(args[0], nested=True)
        if item is not None:
            desc["item"] = item
    elif tag == "dict" and len(args) == 2:
        for key, arg in zip(("key", "value"), args):
            sub = _describe_type(arg, nested=True)
            if sub is not None:
                desc[key] = sub
    return desc


def _build_type(desc: dict[str, Any]) -> Any:
    """Собрать Python-тип по описанию ``_describe_type`` (обратное преобразование).

    Нет ``item``/``key``/``value`` -> голый ``list``/``dict`` (старый payload хаба работает).
    Недостающая половина ``dict`` -> ``Any`` на её месте.
    """
    tag = desc.get("type")
    if tag == "literal":
        choices = tuple(desc.get("choices") or [])
        return Literal[choices] if choices else Literal[None]
    if tag == "list":
        item = _build_nested(desc.get("item"))
        return list if item is None else list[item]
    if tag == "dict":
        key, value = _build_nested(desc.get("key")), _build_nested(desc.get("value"))
        if key is None and value is None:
            return dict
        return dict[Any if key is None else key, Any if value is None else value]
    return _SCALAR_TYPES.get(tag, object)


def _build_nested(desc: Any) -> Any:
    """Вложенное описание -> тип; ``None`` если описания нет или оно пустое (``literal`` без choices)."""
    if not isinstance(desc, dict):
        return None
    if desc.get("type") == "literal" and not desc.get("choices"):
        return None
    return _build_type(desc)


def _json_safe(value: Any) -> Any:
    """Рекурсивно привести значение к JSON-safe виду (никогда не бросает, ревью 1).

    Используется для ``default``, ``choices`` (Literal-плагин с Enum-значениями —
    ``Literal[Color.RED]`` в choices попадал как объект Enum, не JSON-сериализуемый)
    и для КАЖДОГО значения ``meta`` (``FieldMeta(examples=[Path(...)])`` — список внутри
    dict-а метаданных, а не сам ``default``, поэтому старый ``_safe_default`` его не видел).

    ``PydanticUndefined`` -> ``None`` (было: строка ``'PydanticUndefined'`` через общий
    ``str(value)``-фоллбэк — ``Field(default_factory=list)`` оставляет ``default`` этим
    сентинелом до первого построения экземпляра; на границе это «значения нет», а не
    буквальная строка).
    """
    if value is _PYDANTIC_UNDEFINED:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
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
        см. модульный docstring). ``default``/``choices``/КАЖДОЕ значение ``meta`` —
        через ``_json_safe`` (ревью 1): Path/tuple/list/dict конвертируются рекурсивно,
        ``PydanticUndefined`` -> ``None``, неизвестные типы (например Enum в
        ``Literal[Color.RED]``) падают в ``str(value)``, никогда не бросают.
        """
        unwrapped, optional = _unwrap_optional(self.field_type)
        type_desc = _describe_type(unwrapped)
        tag = type_desc["type"]
        meta_dict = self.meta.to_dict() if self.meta is not None else None
        d: dict[str, Any] = {
            "plugin_name": self.plugin_name,
            "field_name": self.field_name,
            "type": tag,
            "optional": optional,
            "default": _json_safe(self.default),
            "meta": _json_safe(meta_dict) if meta_dict is not None else None,
            "category": self.category,
        }
        d.update((k, v) for k, v in type_desc.items() if k != "type")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FieldInfo":
        """Восстановить FieldInfo из ``to_dict()`` — reconstructs Python type по тегу.

        ``unsupported`` восстанавливается как ``object`` (сам по себе классифицируется
        обратно в ``unsupported`` — round-trip тега стабилен, даже если исходный
        Python-тип не переносится через границу). ``list[X]``/``dict[K, V]`` собираются
        из ``item``/``key``/``value`` (Task 1b.2d-1); без них — голый контейнер.
        """
        tag = d["type"]
        optional = bool(d.get("optional", False))
        default = d.get("default")

        field_type: Any = _build_type(d)
        if tag == "tuple3int" and isinstance(default, list):
            default = tuple(default)
        elif tag == "path" and isinstance(default, str):
            default = Path(default)

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
