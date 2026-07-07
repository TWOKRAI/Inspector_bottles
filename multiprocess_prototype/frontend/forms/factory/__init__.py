"""Пакет фабрики Qt-виджетов из Pydantic FieldInfo (разрез god-файла, Task F.5).

Публичный API сохранён ре-экспортами — все существующие импорт-сайты
(`from ...forms.factory import CardsFieldFactory`, а также приватные символы,
которые тянут соседние тесты) работают без правок.

Структура пакета:
    kinds.py            — резолвер kind + Qt-free примитивы
    _common.py          — _make_label (общий Qt-хелпер, лист DAG)
    builders_binding.py — binding-aware builders (FormContext + ActionBus) + _rm_old_value
    builders_legacy.py  — raw Qt-builders + комбинированные диспетчеры (ЖИВОЙ прод-путь)
    json_editor.py      — generic JSON-редактор list/dict

Механизмы построения (raw legacy / FW binding / thin wrapper / json) НЕ
унифицированы — это территория E4/G2 (Ф5). Здесь только вынос по модулям.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

from ..field_editor import FieldEditor
from ._common import _make_label
from .builders_binding import (
    _build_bool_binding_aware,
    _build_color3_binding_aware,
    _build_float_binding_aware,
    _build_int_binding_aware,
    _build_literal_binding_aware,
    _build_path_binding_aware,
    _build_slider_binding_aware,
    _build_str_long_binding_aware,
    _build_str_short_binding_aware,
    _rm_old_value,
)
from .builders_legacy import (
    _build_bool,
    _build_color3,
    _build_float,
    _build_int,
    _build_literal,
    _build_path,
    _build_str_long,
    _build_str_short,
    _build_unsupported,
)
from .json_editor import _JsonTextEdit, _build_json, _json_dumps, _set_json_error
from .kinds import (
    _is_tuple_3int,
    _is_undefined,
    _KIND_BOOL,
    _KIND_COLOR3,
    _KIND_FLOAT,
    _KIND_INT,
    _KIND_JSON,
    _KIND_LITERAL,
    _KIND_PATH,
    _KIND_STR_LONG,
    _KIND_STR_SHORT,
    _KIND_UNSUPPORTED,
    _resolve_kind,
    _safe_default,
    _unwrap_optional,
    _UNDEFINED_TYPES,
    _WIDGET_TO_KIND,
)
from PySide6.QtWidgets import QWidget


# ---------------------------------------------------------------------------
# Реестр builders (kind → builder function)
# ---------------------------------------------------------------------------

_BUILDERS: dict[str, Any] = {  # type: ignore[name-defined]
    _KIND_BOOL: _build_bool,
    _KIND_LITERAL: _build_literal,
    _KIND_COLOR3: _build_color3,
    _KIND_INT: _build_int,
    _KIND_FLOAT: _build_float,
    _KIND_STR_SHORT: _build_str_short,
    _KIND_STR_LONG: _build_str_long,
    _KIND_PATH: _build_path,
    _KIND_JSON: _build_json,
    _KIND_UNSUPPORTED: _build_unsupported,
}


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------


class CardsFieldFactory:
    """Фабрика Qt-виджетов из Pydantic FieldInfo.

    Использование:
        editor = CardsFieldFactory.create(field_info)
        editor.widget   # → QSpinBox / QCheckBox / ...
        editor.getter() # → текущее значение
        editor.setter(42)

    Расширение:
        CardsFieldFactory.register_type("color3", my_custom_builder)
    """

    @classmethod
    def create(
        cls,
        field_info: FieldInfo,
        parent: QWidget | None = None,
        form_ctx: FormContext | None = None,
    ) -> FieldEditor:
        """Создать FieldEditor для данного FieldInfo.

        Определяет kind по типу поля и вызывает соответствующий builder.

        Args:
            field_info: Метаданные поля.
            parent: Родительский Qt-виджет.
            form_ctx: FormContext — единый контекст binding-aware сборки.
                Если передан — bool-поля рендерятся через CheckboxControl,
                int-поля через SpinBoxControl (оба через FormContext.write +
                ActionBus). Legacy callers без form_ctx продолжают работать
                (bool → QCheckBox, int → QSpinBox).
        """
        kind = _resolve_kind(field_info)
        builder = _BUILDERS.get(kind, _build_unsupported)

        # Binding-aware dispatch: bool, int, float, color3 и literal с form_ctx → control-виджеты через ActionBus.
        # Проверяем что builder не был переопределён через register_type().
        if kind == _KIND_BOOL and builder is _build_bool:
            return _build_bool(field_info, parent, form_ctx)
        if kind == _KIND_INT and builder is _build_int:
            return _build_int(field_info, parent, form_ctx=form_ctx)
        if kind == _KIND_FLOAT and builder is _build_float:
            return _build_float(field_info, parent, form_ctx=form_ctx)
        # color3-поля (tuple[int,int,int]) рендерятся через CompoundNumericControl
        # (через FormContext.write + ActionBus) если form_ctx передан.
        if kind == _KIND_COLOR3 and builder is _build_color3:
            return _build_color3(field_info, parent, form_ctx=form_ctx)
        # Literal-поля рендерятся через ComboControl (form_ctx + ActionBus) если form_ctx передан.
        if kind == _KIND_LITERAL and builder is _build_literal:
            return _build_literal(field_info, parent, form_ctx=form_ctx)
        # str/text/path — thin binding wrapper напрямую в factory (без FW-компонента).
        if kind == _KIND_STR_SHORT and builder is _build_str_short:
            return _build_str_short(field_info, parent, form_ctx)
        if kind == _KIND_STR_LONG and builder is _build_str_long:
            return _build_str_long(field_info, parent, form_ctx)
        if kind == _KIND_PATH and builder is _build_path:
            return _build_path(field_info, parent, form_ctx)

        # Fallback: builders без binding-aware пути (unsupported и переопределённые через register_type)
        return builder(field_info, parent)

    @classmethod
    def register_type(
        cls,
        type_key: str,
        builder: Any,  # type: ignore[name-defined]
    ) -> None:
        """Зарегистрировать или переопределить builder для kind.

        Аргументы:
            type_key: строковый ключ kind (например, "color3", "int").
            builder: функция (field_info, parent) -> FieldEditor.
        """
        _BUILDERS[type_key] = builder

    @classmethod
    def resolve_kind(cls, field_info: FieldInfo) -> str:
        """Публичный доступ к определению kind (для тестирования)."""
        return _resolve_kind(field_info)


__all__ = [
    "CardsFieldFactory",
    # Приватные символы, которые импортируют соседние тесты/сайты — ре-экспорт.
    "_BUILDERS",
    "_resolve_kind",
    "_make_label",
    "_safe_default",
    "_unwrap_optional",
    "_is_tuple_3int",
    "_is_undefined",
    "_WIDGET_TO_KIND",
    "_UNDEFINED_TYPES",
    "_KIND_BOOL",
    "_KIND_LITERAL",
    "_KIND_COLOR3",
    "_KIND_INT",
    "_KIND_FLOAT",
    "_KIND_STR_SHORT",
    "_KIND_STR_LONG",
    "_KIND_PATH",
    "_KIND_JSON",
    "_KIND_UNSUPPORTED",
    "_build_bool",
    "_build_literal",
    "_build_color3",
    "_build_int",
    "_build_float",
    "_build_str_short",
    "_build_str_long",
    "_build_path",
    "_build_json",
    "_build_unsupported",
    "_build_bool_binding_aware",
    "_build_int_binding_aware",
    "_build_slider_binding_aware",
    "_build_color3_binding_aware",
    "_build_literal_binding_aware",
    "_build_float_binding_aware",
    "_build_str_short_binding_aware",
    "_build_str_long_binding_aware",
    "_build_path_binding_aware",
    "_rm_old_value",
    "_JsonTextEdit",
    "_json_dumps",
    "_set_json_error",
]
