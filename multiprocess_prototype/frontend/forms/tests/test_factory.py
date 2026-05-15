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


# ---------------------------------------------------------------------------
# Phase 2.0 pilot: bool через form_ctx → CheckboxControl
# ---------------------------------------------------------------------------


class TestCardsFieldFactoryFormCtx:
    """Тесты для bool через form_ctx (binding-aware CheckboxControl)."""

    @staticmethod
    def _make_form_ctx():
        """Собрать FormBuildingContext с фейковым RM и реальным ActionBus."""
        from dataclasses import dataclass
        from typing import Any

        from multiprocess_framework.modules.actions_module.bus import ActionBus
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
        from multiprocess_prototype.frontend.actions.handlers.field_set_handler import (
            FieldSetHandler,
        )
        from multiprocess_prototype.frontend.forms.factory import FormBuildingContext

        @dataclass
        class _FakeReg:
            enabled: bool = False

        class _FakeRM:
            def __init__(self):
                self._regs = {"test": _FakeReg()}
                self._subs: dict[tuple, list] = {}

            def get_register(self, name: str) -> Any:
                return self._regs.get(name)

            def get_field_metadata(self, register_name: str, field_name: str, **kw: Any) -> dict:
                return {"description": "test field"}

            def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
                reg = self.get_register(register_name)
                if not reg:
                    return False, "no reg"
                setattr(reg, field_name, value)
                for cb in list(self._subs.get((register_name, field_name), [])):
                    cb(value)
                return True, None

            def subscribe(self, reg: str, field: str, cb: Any) -> None:
                self._subs.setdefault((reg, field), []).append(cb)

            def unsubscribe(self, reg: str, field: str, cb: Any) -> None:
                lst = self._subs.get((reg, field))
                if lst and cb in lst:
                    lst.remove(cb)

        rm = _FakeRM()
        bus = ActionBus(rm, max_history=50)
        bus.register_handler("field_set", FieldSetHandler())
        ctx = FormBuildingContext(
            registers_manager=rm,
            action_bus=bus,
            action_builder=V2ActionBuilder,
        )
        return ctx, rm, bus

    def test_bool_with_form_ctx_creates_checkbox_view(self, qtbot):
        """bool + form_ctx → CheckboxView (не QCheckBox)."""
        from multiprocess_framework.modules.frontend_module.components.checkbox.view import (
            CheckboxView,
        )

        ctx, rm, bus = self._make_form_ctx()
        fi = _fi(bool, default=False, plugin_name="test", field_name="enabled")
        editor = CardsFieldFactory.create(fi, form_ctx=ctx)
        qtbot.addWidget(editor.widget)

        assert isinstance(editor.widget, CheckboxView)
        # getter/setter работают
        assert editor.getter() is False
        editor.setter(True)
        assert editor.getter() is True

    def test_bool_with_form_ctx_toggle_creates_action(self, qtbot):
        """bool + form_ctx: toggle → action в undo_stack."""
        ctx, rm, bus = self._make_form_ctx()
        fi = _fi(bool, default=False, plugin_name="test", field_name="enabled")
        editor = CardsFieldFactory.create(fi, form_ctx=ctx)
        qtbot.addWidget(editor.widget)

        # Эмулировать пользовательский toggle через set_value (не silent)
        editor.widget.set_value(True)

        assert bus.can_undo() is True
        last = bus.last_action()
        assert last is not None
        assert last.action_type == "field_set"
        assert last.forward_patch["value"] is True

    def test_legacy_bool_without_form_ctx_no_deprecation_in_phase2(self, qtbot):
        """bool без form_ctx → QCheckBox, но DeprecationWarning НЕ эмитится в Phase 2.0.

        Warning деактивирован до Phase 2.6, когда form_ctx станет обязательным.
        """
        import warnings

        fi = _fi(bool, default=False)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            editor = CardsFieldFactory.create(fi)
            qtbot.addWidget(editor.widget)

        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0, "DeprecationWarning не должен эмититься в Phase 2.0"
        assert isinstance(editor.widget, QCheckBox)


# ---------------------------------------------------------------------------
# Regression: алиасы widget нормализуются в FieldMeta, factory читает canonical
# ---------------------------------------------------------------------------


class TestWidgetAliasNormalization:
    """FieldMeta нормализует алиасы до factory — единый источник истины."""

    def test_combo_alias_resolves_to_literal_kind(self):
        """widget=combo → нормализуется в literal в FieldMeta → kind=literal в factory."""
        meta = FieldMeta(widget="combo")  # после __init__: meta.widget == "literal"
        assert meta.widget == "literal"
        fi = _fi(str, default="a", meta=meta)
        assert CardsFieldFactory.resolve_kind(fi) == "literal"
