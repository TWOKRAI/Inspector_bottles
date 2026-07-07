# -*- coding: utf-8 -*-
"""Характеризационные тесты фабрики форм (Трек F, Task F.5).

Фиксируют ТЕКУЩЕЕ наблюдаемое поведение `CardsFieldFactory` ДО разреза
god-файла `forms/factory.py` (1190 LOC) на пакет.

Фокус — ЖИВОЙ прод-путь легаси (form_ctx=None): по вердикту №5 GATE G0 именно
legacy-путь фабрики — единственный используемый в проде (form_ctx=None во всех
сайтах); binding-aware ветки прод-мертвы, но их код НЕ трогается (территория
E4/G2 в Ф5). Поэтому здесь замораживаем:

    * резолвер kind (Qt-free таблица type/meta.widget → kind);
    * построение виджетов по kind на легаси-пути (тип виджета, getter==default,
      setter→getter roundtrip, наличие/отсутствие change_signal);
    * generic JSON-редактор (кэш последнего валидного значения, красная рамка,
      пустой текст → default, roundtrip);
    * identity-контракт register_type (переопределённый builder зовётся БЕЗ
      form_ctx).

Цель — не «улучшить», а заморозить поведение. После разреза (Task F.5, второй
коммит) эти тесты обязаны пройти БЕЗ правок ожиданий — они и есть контракт
разреза. Публичные приватные символы (`_BUILDERS`, `_KIND_*`, `_build_*`,
`_resolve_kind`), которые импортируют другие тесты, здесь тоже прощупываются на
сохранность после превращения модуля в пакет с ре-экспортами.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo
from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory


# --------------------------------------------------------------------------- #
#  Фабрика FieldInfo                                                           #
# --------------------------------------------------------------------------- #


def _fi(
    field_type: type,
    default: Any = None,
    meta: FieldMeta | None = None,
    field_name: str = "test_field",
    plugin_name: str = "test",
    category: str = "",
) -> FieldInfo:
    """Быстрое создание FieldInfo для тестов (зеркалит хелпер test_factory.py)."""
    return FieldInfo(
        plugin_name=plugin_name,
        field_name=field_name,
        field_type=field_type,
        default=default,
        meta=meta,
        category=category,
    )


# --------------------------------------------------------------------------- #
#  Резолвер kind — Qt-free таблица                                             #
# --------------------------------------------------------------------------- #


class TestResolveKind:
    """Замораживает порядок и результат резолва kind по типу/meta.widget."""

    def test_bool_before_int(self):
        """bool резолвится в 'bool', НЕ в 'int' (bool — подкласс int)."""
        assert CardsFieldFactory.resolve_kind(_fi(bool, default=True)) == "bool"

    def test_optional_int_unwraps(self):
        """Optional[int] → 'int' (Optional снимается)."""
        assert CardsFieldFactory.resolve_kind(_fi(Optional[int], default=1)) == "int"

    def test_literal(self):
        """Literal[...] → 'literal'."""
        assert CardsFieldFactory.resolve_kind(_fi(Literal["a", "b"], default="a")) == "literal"

    def test_tuple_3int_is_color3(self):
        """tuple[int,int,int] → 'color3'."""
        assert CardsFieldFactory.resolve_kind(_fi(tuple[int, int, int], default=(0, 0, 0))) == "color3"

    def test_plain_int(self):
        assert CardsFieldFactory.resolve_kind(_fi(int, default=3)) == "int"

    def test_plain_float(self):
        assert CardsFieldFactory.resolve_kind(_fi(float, default=1.5)) == "float"

    def test_str_short(self):
        """str с коротким default → 'str_short'."""
        assert CardsFieldFactory.resolve_kind(_fi(str, default="hi")) == "str_short"

    def test_str_long_over_120(self):
        """str с default длиннее 120 символов → 'str_long'."""
        assert CardsFieldFactory.resolve_kind(_fi(str, default="x" * 121)) == "str_long"

    def test_str_exactly_120_stays_short(self):
        """Граница: ровно 120 символов остаётся 'str_short' (>120 — строгое)."""
        assert CardsFieldFactory.resolve_kind(_fi(str, default="x" * 120)) == "str_short"

    def test_path(self):
        assert CardsFieldFactory.resolve_kind(_fi(Path, default=Path("/tmp"))) == "path"

    def test_list_is_json(self):
        assert CardsFieldFactory.resolve_kind(_fi(list, default=[])) == "json"

    def test_dict_is_json(self):
        assert CardsFieldFactory.resolve_kind(_fi(dict, default={})) == "json"

    def test_parametrized_list_dict_is_json(self):
        assert CardsFieldFactory.resolve_kind(_fi(list[dict[str, int]], default=[])) == "json"

    def test_optional_dict_is_json(self):
        assert CardsFieldFactory.resolve_kind(_fi(Optional[dict], default=None)) == "json"

    def test_meta_widget_slider_maps_to_int(self):
        """meta.widget='slider' → kind 'int' (slider — UI-вариант int до Phase 2.4)."""
        fi = _fi(int, default=5, meta=FieldMeta(widget="slider"))
        assert CardsFieldFactory.resolve_kind(fi) == "int"

    def test_meta_widget_label_maps_to_unsupported(self):
        """meta.widget='label' → kind 'unsupported'."""
        fi = _fi(int, default=0, meta=FieldMeta(widget="label"))
        assert CardsFieldFactory.resolve_kind(fi) == "unsupported"

    def test_unknown_widget_falls_back_to_type_dispatch(self):
        """Неизвестный meta.widget → graceful fallback на type-dispatch."""
        fi = _fi(bool, default=False, meta=FieldMeta(widget="totally_unknown_xyz"))
        assert CardsFieldFactory.resolve_kind(fi) == "bool"

    def test_unknown_type_is_unsupported(self):
        """Неизвестный тип (set) → 'unsupported'."""
        assert CardsFieldFactory.resolve_kind(_fi(set, default=set())) == "unsupported"


# --------------------------------------------------------------------------- #
#  Легаси-построение виджетов (form_ctx=None) — ЖИВОЙ прод-путь                #
# --------------------------------------------------------------------------- #


class TestLegacyBuilders:
    """create(fi) без form_ctx: тип виджета, getter==default, roundtrip, change_signal."""

    def test_bool(self, qtbot):
        editor = CardsFieldFactory.create(_fi(bool, default=True))
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QCheckBox)
        assert editor.getter() is True
        editor.setter(False)
        assert editor.getter() is False
        assert editor.change_signal is not None  # toggled

    def test_int(self, qtbot):
        fi = _fi(int, default=90, meta=FieldMeta("Угол", min=0, max=179, unit="°"))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QSpinBox)
        assert editor.widget.minimum() == 0
        assert editor.widget.maximum() == 179
        assert editor.widget.suffix() == " °"
        assert editor.getter() == 90
        editor.setter(42)
        assert editor.getter() == 42
        assert editor.change_signal is not None  # valueChanged

    def test_int_no_meta_wide_range(self, qtbot):
        editor = CardsFieldFactory.create(_fi(int, default=7))
        qtbot.addWidget(editor.widget)
        assert editor.widget.minimum() == -(2**31)
        assert editor.widget.maximum() == 2**31 - 1
        assert editor.getter() == 7

    def test_slider_meta_renders_legacy_spinbox(self, qtbot):
        """meta.widget='slider' на легаси-пути → raw QSpinBox (slider UI отложен)."""
        fi = _fi(int, default=5, meta=FieldMeta(widget="slider", min=0, max=10))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QSpinBox)
        assert editor.getter() == 5

    def test_float(self, qtbot):
        fi = _fi(float, default=3.14, meta=FieldMeta("V", min=0.0, max=100.0, round_k=2, unit="м"))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QDoubleSpinBox)
        assert editor.widget.decimals() == 2
        assert editor.widget.suffix() == " м"
        editor.setter(2.5)
        assert editor.getter() == pytest.approx(2.5)
        assert editor.change_signal is not None  # valueChanged

    def test_literal(self, qtbot):
        fi = _fi(Literal["a", "b", "c"], default="b")
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QComboBox)
        items = [editor.widget.itemText(i) for i in range(editor.widget.count())]
        assert items == ["a", "b", "c"]
        assert editor.getter() == "b"
        editor.setter("c")
        assert editor.getter() == "c"
        assert editor.change_signal is not None  # currentTextChanged

    def test_color3(self, qtbot):
        """tuple[int,int,int] legacy → QWidget с 3 QSpinBox (0..255), change_signal=None."""
        fi = _fi(tuple[int, int, int], default=(100, 200, 50))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QWidget)
        spins = editor.widget.findChildren(QSpinBox)
        assert len(spins) == 3
        assert editor.getter() == (100, 200, 50)
        editor.setter((1, 2, 3))
        assert editor.getter() == (1, 2, 3)
        assert editor.change_signal is None

    def test_str_short(self, qtbot):
        editor = CardsFieldFactory.create(_fi(str, default="hello"))
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QLineEdit)
        assert editor.getter() == "hello"
        editor.setter("world")
        assert editor.getter() == "world"
        assert editor.change_signal is not None  # textChanged

    def test_str_long_readonly(self, qtbot):
        long_text = "x" * 150
        editor = CardsFieldFactory.create(_fi(str, default=long_text))
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QPlainTextEdit)
        assert editor.widget.isReadOnly()
        assert editor.getter() == long_text
        assert editor.change_signal is not None  # textChanged

    def test_path(self, qtbot):
        editor = CardsFieldFactory.create(_fi(Path, default=Path("/tmp/test")))
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QLineEdit)
        assert editor.getter() == "/tmp/test"
        editor.setter("/etc")
        assert editor.getter() == "/etc"
        assert editor.change_signal is not None  # textChanged

    def test_unsupported_disabled_label(self, qtbot):
        editor = CardsFieldFactory.create(_fi(set, default={1, 2, 3}))
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QLabel)
        assert not editor.widget.isEnabled()
        assert editor.getter() == {1, 2, 3}
        # setter — noop, не падает
        editor.setter("ignored")
        assert editor.getter() == {1, 2, 3}
        assert editor.change_signal is None

    def test_label_includes_unit(self, qtbot):
        fi = _fi(int, default=0, meta=FieldMeta("Угол", unit="°"))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)
        assert "Угол" in editor.label.text()
        assert "°" in editor.label.text()


# --------------------------------------------------------------------------- #
#  Generic JSON-редактор (list/dict) — ключевой контракт кэша                  #
# --------------------------------------------------------------------------- #


class TestJsonEditor:
    """committed на потерю фокуса; getter парсит; кэш последнего валидного значения."""

    def test_list_dict_creates_plaintext_and_parses(self, qtbot):
        regions = [{"name": "left", "x": 0, "y": 0, "width": 320, "height": 480}]
        editor = CardsFieldFactory.create(_fi(list[dict[str, Any]], default=regions))
        qtbot.addWidget(editor.widget)
        assert isinstance(editor.widget, QPlainTextEdit)
        assert editor.getter() == regions
        assert editor.change_signal is not None  # committed

    def test_getter_parses_edited_text(self, qtbot):
        editor = CardsFieldFactory.create(_fi(list, default=[]))
        qtbot.addWidget(editor.widget)
        editor.widget.setPlainText('[{"x": 1}, {"x": 2}]')
        assert editor.getter() == [{"x": 1}, {"x": 2}]

    def test_invalid_json_returns_last_valid_and_marks_error(self, qtbot):
        """Невалидный JSON → getter возвращает последнее валидное значение + красная рамка."""
        editor = CardsFieldFactory.create(_fi(list, default=[]))
        qtbot.addWidget(editor.widget)
        editor.setter([{"a": 1}])
        editor.widget.setPlainText("{ это не json")
        assert editor.getter() == [{"a": 1}]
        assert "c0392b" in editor.widget.styleSheet()  # красная рамка
        assert editor.widget.toolTip() != ""

    def test_empty_text_returns_default(self, qtbot):
        editor = CardsFieldFactory.create(_fi(dict, default={"k": 1}))
        qtbot.addWidget(editor.widget)
        editor.widget.setPlainText("")
        assert editor.getter() == {"k": 1}

    def test_setter_serializes_and_clears_error(self, qtbot):
        editor = CardsFieldFactory.create(_fi(list, default=[]))
        qtbot.addWidget(editor.widget)
        editor.setter([{"name": "right"}])
        assert "right" in editor.widget.toPlainText()
        assert editor.widget.styleSheet() == ""


# --------------------------------------------------------------------------- #
#  register_type — identity-контракт                                          #
# --------------------------------------------------------------------------- #


class TestRegisterTypeIdentity:
    """Переопределённый через register_type builder зовётся БЕЗ form_ctx."""

    def test_override_called_without_form_ctx(self, qtbot):
        from multiprocess_prototype.frontend.forms.factory import _BUILDERS, _KIND_INT

        original = _BUILDERS[_KIND_INT]
        try:
            seen: dict[str, Any] = {"calls": 0, "argc": None}

            def custom_int_builder(field_info, parent=None):
                seen["calls"] += 1
                # Если бы create() передал form_ctx третьим позиционным — упало бы.
                return original(field_info, parent)

            CardsFieldFactory.register_type("int", custom_int_builder)

            # form_ctx НЕ передаём (легаси) — всё равно кастомный builder.
            editor = CardsFieldFactory.create(_fi(int, default=1))
            qtbot.addWidget(editor.widget)
            assert seen["calls"] == 1
            assert isinstance(editor.widget, QSpinBox)
        finally:
            _BUILDERS[_KIND_INT] = original


# --------------------------------------------------------------------------- #
#  Сохранность приватного API (импорт-контракт для соседних тестов)           #
# --------------------------------------------------------------------------- #


class TestPrivateApiSurface:
    """Символы, которые импортируют другие тесты/сайты, доступны из пакета."""

    def test_kind_constants_and_builders_importable(self):
        from multiprocess_prototype.frontend.forms import factory as f

        for name in (
            "_BUILDERS",
            "_KIND_BOOL",
            "_KIND_INT",
            "_KIND_JSON",
            "_resolve_kind",
            "_build_str_short",
            "_build_str_long",
            "_build_path",
        ):
            assert hasattr(f, name), f"factory.{name} должен быть доступен"

    def test_builders_registry_covers_all_kinds(self):
        from multiprocess_prototype.frontend.forms.factory import (
            _BUILDERS,
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
        )

        for kind in (
            _KIND_BOOL,
            _KIND_LITERAL,
            _KIND_COLOR3,
            _KIND_INT,
            _KIND_FLOAT,
            _KIND_STR_SHORT,
            _KIND_STR_LONG,
            _KIND_PATH,
            _KIND_JSON,
            _KIND_UNSUPPORTED,
        ):
            assert kind in _BUILDERS
