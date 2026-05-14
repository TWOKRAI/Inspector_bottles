"""Тесты CardsFieldFactory — маппинг type → widget (~12 тестов)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
)

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory
from multiprocess_prototype.frontend.forms.widgets.color_picker import ColorTripletWidget
from multiprocess_prototype.registers.field_info import FieldInfo


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _fi(
    field_type: type,
    default=None,
    meta: FieldMeta | None = None,
    field_name: str = "test_field",
    plugin_name: str = "test",
    category: str = "",
) -> FieldInfo:
    """Быстрое создание FieldInfo для тестов."""
    return FieldInfo(
        plugin_name=plugin_name,
        field_name=field_name,
        field_type=field_type,
        default=default,
        meta=meta,
        category=category,
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestCardsFieldFactory:
    """Тесты маппинга type → widget."""

    def test_bool_creates_checkbox(self, qtbot):
        """bool → QCheckBox."""
        fi = _fi(bool, default=True)
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QCheckBox)
        assert editor.getter() is True

    def test_bool_default_true_is_checked(self, qtbot):
        """bool, default=True → QCheckBox.isChecked() == True."""
        fi = _fi(bool, default=True)
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert editor.widget.isChecked() is True

    def test_bool_setter(self, qtbot):
        """setter меняет checked-состояние."""
        fi = _fi(bool, default=False)
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        editor.setter(True)
        assert editor.getter() is True

    def test_int_creates_spinbox_with_range_and_suffix(self, qtbot):
        """int + meta(min=0,max=179,unit='°') → QSpinBox с range (0,179) и suffix ' °'."""
        fi = _fi(int, default=90, meta=FieldMeta("Угол", min=0, max=179, unit="°"))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QSpinBox)
        assert editor.widget.minimum() == 0
        assert editor.widget.maximum() == 179
        assert editor.widget.suffix() == " °"
        assert editor.getter() == 90

    def test_int_no_meta_uses_defaults(self, qtbot):
        """int без FieldMeta → QSpinBox с широким диапазоном."""
        fi = _fi(int, default=42)
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QSpinBox)
        assert editor.widget.minimum() == -(2**31)
        assert editor.widget.maximum() == 2**31 - 1
        assert editor.getter() == 42

    def test_float_creates_double_spinbox_with_decimals(self, qtbot):
        """float + meta(round_k=2) → QDoubleSpinBox с 2 decimals."""
        fi = _fi(float, default=3.14, meta=FieldMeta("Значение", min=0.0, max=100.0, round_k=2, unit="м"))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QDoubleSpinBox)
        assert editor.widget.decimals() == 2
        assert editor.widget.minimum() == 0.0
        assert editor.widget.maximum() == 100.0
        assert editor.widget.suffix() == " м"

    def test_literal_creates_combobox(self, qtbot):
        """Literal['a','b','c'] → QComboBox с 3 элементами в порядке объявления."""
        fi = _fi(Literal["a", "b", "c"], default="b")
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QComboBox)
        assert editor.widget.count() == 3
        items = [editor.widget.itemText(i) for i in range(editor.widget.count())]
        assert items == ["a", "b", "c"]
        assert editor.getter() == "b"

    def test_color3_creates_triplet_widget(self, qtbot):
        """tuple[int,int,int] → ColorTripletWidget с 3 спинбоксами 0..255."""
        fi = _fi(tuple[int, int, int], default=(100, 200, 50))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, ColorTripletWidget)
        assert editor.getter() == (100, 200, 50)

    def test_str_short_creates_lineedit(self, qtbot):
        """str (короткая) → QLineEdit."""
        fi = _fi(str, default="hello")
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QLineEdit)
        assert editor.getter() == "hello"

    def test_str_long_creates_plaintextedit(self, qtbot):
        """str > 120 символов → QPlainTextEdit (read-only)."""
        long_text = "x" * 150
        fi = _fi(str, default=long_text)
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QPlainTextEdit)
        assert editor.widget.isReadOnly()
        assert editor.getter() == long_text

    def test_unsupported_creates_disabled_label(self, qtbot):
        """Неподдерживаемый тип → disabled QLabel, не падает."""
        fi = _fi(dict, default={"key": "value"})
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QLabel)
        assert not editor.widget.isEnabled()
        assert editor.getter() == {"key": "value"}

    def test_optional_int_unwraps_to_spinbox(self, qtbot):
        """Optional[int] → QSpinBox (Optional снимается)."""
        fi = _fi(Optional[int], default=10)
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QSpinBox)
        assert editor.getter() == 10

    def test_path_creates_lineedit(self, qtbot):
        """Path → QLineEdit."""
        fi = _fi(Path, default=Path("/tmp/test"))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, QLineEdit)
        assert editor.getter() == "/tmp/test"

    def test_register_type_overrides_builder(self, qtbot):
        """register_type() переопределяет builder для kind."""
        # Запомним оригинальный builder
        from multiprocess_prototype.frontend.forms.factory import _BUILDERS, _KIND_BOOL

        original = _BUILDERS[_KIND_BOOL]

        try:
            call_count = [0]

            def custom_bool_builder(field_info, parent=None):
                call_count[0] += 1
                return original(field_info, parent)

            CardsFieldFactory.register_type("bool", custom_bool_builder)

            fi = _fi(bool, default=False)
            editor = CardsFieldFactory.create(fi)
            qtbot.addWidget(editor.widget)

            assert call_count[0] == 1
            assert isinstance(editor.widget, QCheckBox)
        finally:
            # Восстановить оригинальный builder
            _BUILDERS[_KIND_BOOL] = original

    def test_label_includes_unit(self, qtbot):
        """Label содержит unit в скобках: 'Угол (°)'."""
        fi = _fi(int, default=0, meta=FieldMeta("Угол", unit="°"))
        editor = CardsFieldFactory.create(fi)
        qtbot.addWidget(editor.widget)

        assert "°" in editor.label.text()
        assert "Угол" in editor.label.text()
