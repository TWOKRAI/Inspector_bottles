"""Резолвер kind и Qt-free примитивы фабрики форм.

Выделено из `forms/factory.py` (Task F.5, дословный перенос). Здесь только
логика «тип поля → kind» и вспомогательные функции над FieldInfo — без создания
Qt-виджетов, поэтому `_resolve_kind` тестируется без QApplication.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


# ---------------------------------------------------------------------------
# Sentinel для pydantic_core.PydanticUndefined (чтобы не тянуть зависимость)
# ---------------------------------------------------------------------------
_UNDEFINED_TYPES: tuple[type, ...] = ()
try:
    from pydantic_core import PydanticUndefined  # type: ignore[attr-defined]

    _UNDEFINED_TYPES = (type(PydanticUndefined),)
except ImportError:
    pass


def _is_undefined(value: Any) -> bool:
    """True если value — PydanticUndefined или None."""
    if value is None:
        return True
    if _UNDEFINED_TYPES and isinstance(value, _UNDEFINED_TYPES):
        return True
    # Проверка по repr на случай другой версии pydantic
    return repr(value) == "PydanticUndefined"


def _safe_default(field_info: FieldInfo, fallback: Any = None) -> Any:
    """Получить default или fallback, если default == PydanticUndefined / None."""
    val = field_info.default
    if _is_undefined(val):
        return fallback
    return val


# ---------------------------------------------------------------------------
# Резолвер kind из field_type
# ---------------------------------------------------------------------------

# Возможные kind-ы (порядок резолва критичен — см. _resolve_kind)
_KIND_BOOL = "bool"
_KIND_LITERAL = "literal"
_KIND_COLOR3 = "color3"
_KIND_INT = "int"
_KIND_FLOAT = "float"
_KIND_STR_SHORT = "str_short"
_KIND_STR_LONG = "str_long"
_KIND_PATH = "path"
_KIND_JSON = "json"
_KIND_UNSUPPORTED = "unsupported"


def _unwrap_optional(t: type) -> type:
    """Снять Optional[X] → X. Если не Optional — вернуть as-is."""
    origin = get_origin(t)
    if origin is type(None):
        return type(None)
    # Union[X, None] — это Optional[X]
    import types as _types

    _union_reprs = ("typing.Union", "<class 'types.UnionType'>")
    if origin is _types.UnionType or (origin is not None and repr(origin) in _union_reprs):
        args = get_args(t)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return t


def _is_tuple_3int(t: type) -> bool:
    """Проверить, что тип == tuple[int, int, int]."""
    origin = get_origin(t)
    if origin is not tuple:
        return False
    args = get_args(t)
    return len(args) == 3 and all(a is int for a in args)


# Маппинг канонических widget → внутренняя kind-константа.
# Алиасы (combo/spinbox/numeric) нормализуются в FieldMeta.__init__ —
# здесь только канонические значения + slider (отдельный UI hint для Phase 2.4).
_WIDGET_TO_KIND: dict[str, str] = {
    "checkbox": _KIND_BOOL,
    "literal": _KIND_LITERAL,
    "color3": _KIND_COLOR3,
    "slider": _KIND_INT,  # slider — UI variant int, до Phase 2.4 рендерится как _build_int
    "int": _KIND_INT,
    "float": _KIND_FLOAT,
    "str": _KIND_STR_SHORT,
    "text": _KIND_STR_LONG,
    "path": _KIND_PATH,
    "json": _KIND_JSON,
    "label": _KIND_UNSUPPORTED,
    # Кастомный kind: builder регистрируется извне через register_type("model_picker", ...).
    # Без зарегистрированного builder'а _BUILDERS.get вернёт _build_unsupported (graceful).
    "model_picker": "model_picker",
}


def _resolve_kind(field_info: FieldInfo) -> str:
    """Определить kind виджета по типу поля.

    Порядок проверок критичен — более специфичные типы проверяются первыми.
    Перед type-based dispatch проверяется FieldMeta.widget — явный override
    позволяет требовать slider для int с диапазоном или label для bool.
    """
    # 0. Явный FieldMeta.widget перекрывает type-dispatch.
    # FieldMeta.__init__ нормализует алиасы (combo→literal, spinbox→int, numeric→float),
    # поэтому здесь всегда каноническое значение.
    meta = field_info.meta
    widget = getattr(meta, "widget", "") if meta is not None else ""
    if widget:
        # Неизвестный widget → graceful fallback на type-dispatch.
        kind = _WIDGET_TO_KIND.get(widget)
        if kind is not None:
            return kind

    t = _unwrap_optional(field_info.field_type)

    # 1. bool ДО int (bool — подкласс int в Python)
    if t is bool:
        return _KIND_BOOL

    # 2. Literal
    if get_origin(t) is Literal:
        return _KIND_LITERAL

    # 3. tuple[int, int, int] — цветовой триплет
    if _is_tuple_3int(t):
        return _KIND_COLOR3

    # 4. int
    if t is int:
        return _KIND_INT

    # 5. float
    if t is float:
        return _KIND_FLOAT

    # 6. str (короткая / длинная)
    if t is str:
        default = field_info.default
        if isinstance(default, str) and len(default) > 120:
            return _KIND_STR_LONG
        return _KIND_STR_SHORT

    # 7. Path
    if t is Path:
        return _KIND_PATH

    # 8. list / dict (в т.ч. параметризованные list[...], dict[...]) → generic JSON-редактор
    if t in (dict, list) or get_origin(t) in (dict, list):
        return _KIND_JSON

    # 9. Всё остальное
    return _KIND_UNSUPPORTED
