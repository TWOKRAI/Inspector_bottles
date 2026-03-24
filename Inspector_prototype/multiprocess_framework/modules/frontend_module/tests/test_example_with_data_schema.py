# -*- coding: utf-8 -*-
"""Тесты учебного пакета control_v2.examples (бывш. example_with_data_schema)."""
from __future__ import annotations

import pytest

from frontend_module.components.examples.checkbox import (
    ExampleCheckboxUiConfig,
    ExampleCheckboxValueRegister,
    checkbox_binding,
    checkbox_view_config_from_ui,
    coerce_ui as checkbox_coerce_ui,
    create_example_checkbox,
)
from frontend_module.components.examples.compound_mixed import (
    ExampleCompoundMixedUiConfig,
    ExampleMixedBoolRegister,
    ExampleMixedFloatRegister,
    create_example_compound_mixed,
)
from frontend_module.components.examples.compound_numeric import (
    ExampleBgrTripletRegister,
    ExampleCompoundNumericUiConfig,
    compound_numeric_binding,
    compound_numeric_view_config_from_ui,
    create_example_compound_numeric,
)
from frontend_module.components.examples.group import (
    ExampleGroupRowUiConfig,
    create_example_group_row,
    coerce_ui as group_row_coerce_ui,
)
from frontend_module.components.examples.label import (
    ExampleLabelUiConfig,
    create_example_label,
    label_config_from_ui,
)
from frontend_module.components.examples.numeric import (
    ExampleNumericUiConfig,
    ExampleNumericValueRegister,
    create_example_numeric,
    numeric_binding,
    numeric_view_config_from_ui,
)
from frontend_module.components.examples.slider import (
    ExampleSliderUiConfig,
    ExampleSliderValueRegister,
    coerce_ui as slider_coerce_ui,
    create_example_slider,
    slider_binding,
    slider_view_config_from_ui,
)
from frontend_module.components.examples.spinbox import (
    ExampleSpinboxUiConfig,
    ExampleSpinboxValueRegister,
    create_example_spinbox,
    spinbox_binding,
    spinbox_view_config_from_ui,
)


class TestCheckboxSchemas:
    def test_value_register_default(self) -> None:
        m = ExampleCheckboxValueRegister()
        assert m.feature_enabled is False

    def test_ui_config_defaults(self) -> None:
        u = ExampleCheckboxUiConfig()
        assert u.checkbox_label == ""
        assert u.checkbox_position == "left"

    def test_coerce_dict(self) -> None:
        u = checkbox_coerce_ui({"checkbox_label": "X", "checkbox_position": "right"})
        assert u.checkbox_label == "X"
        assert u.checkbox_position == "right"


class TestCheckboxAdapter:
    def test_binding_uses_schema_keys(self) -> None:
        b = checkbox_binding()
        assert b.register_name == ExampleCheckboxValueRegister.BINDING_REGISTER
        assert b.field_name == ExampleCheckboxValueRegister.BINDING_FIELD

    def test_view_config_empty_label_none(self) -> None:
        u = ExampleCheckboxUiConfig()
        vc = checkbox_view_config_from_ui(u)
        assert vc.label is None
        assert vc.position == "left"

    def test_view_config_label_strip(self) -> None:
        u = ExampleCheckboxUiConfig(checkbox_label="  Демо  ")
        vc = checkbox_view_config_from_ui(u)
        assert vc.label == "Демо"


class TestSliderSchemas:
    def test_value_register_default(self) -> None:
        m = ExampleSliderValueRegister()
        assert m.demo_threshold == 50.0

    def test_ui_config_defaults(self) -> None:
        u = ExampleSliderUiConfig()
        assert u.slider_label == ""
        assert u.slider_position == "left"
        assert u.slider_show_ticks is False

    def test_coerce_dict(self) -> None:
        u = slider_coerce_ui({"slider_label": "X", "slider_position": "right"})
        assert u.slider_label == "X"
        assert u.slider_position == "right"


class TestSliderAdapter:
    def test_binding_uses_schema_keys(self) -> None:
        b = slider_binding()
        assert b.register_name == ExampleSliderValueRegister.BINDING_REGISTER
        assert b.field_name == ExampleSliderValueRegister.BINDING_FIELD

    def test_view_config_empty_label_none(self) -> None:
        u = ExampleSliderUiConfig()
        vc = slider_view_config_from_ui(u)
        assert vc.label is None
        assert vc.label_position == "left"

    def test_view_config_label_strip(self) -> None:
        u = ExampleSliderUiConfig(slider_label="  Порог  ")
        vc = slider_view_config_from_ui(u)
        assert vc.label == "Порог"


@pytest.fixture
def qapp():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestCreateExampleCheckbox:
    def test_create_smoke(self, qapp) -> None:
        r = create_example_checkbox(
            None, ExampleCheckboxUiConfig(checkbox_label="L")
        )
        assert r.widget is not None
        assert r.presenter is not None


class TestCreateExampleSlider:
    def test_create_smoke(self, qapp) -> None:
        r = create_example_slider(
            None,
            ExampleSliderUiConfig(slider_label="L", slider_show_ticks=True),
        )
        assert r.widget is not None
        assert r.presenter is not None


class TestSpinboxSchemas:
    def test_defaults(self) -> None:
        assert ExampleSpinboxValueRegister().demo_spinbox_value == 25.0
        u = ExampleSpinboxUiConfig()
        assert u.spinbox_position == "left"


class TestSpinboxAdapter:
    def test_binding(self) -> None:
        b = spinbox_binding()
        assert b.field_name == ExampleSpinboxValueRegister.BINDING_FIELD

    def test_view_config(self) -> None:
        vc = spinbox_view_config_from_ui(ExampleSpinboxUiConfig(spinbox_label="  x  "))
        assert vc.label == "x"


class TestCreateExampleSpinbox:
    def test_create_smoke(self, qapp) -> None:
        r = create_example_spinbox(None, ExampleSpinboxUiConfig(spinbox_label="S"))
        assert r.widget is not None
        assert r.presenter is not None


class TestCompoundNumericSchemas:
    def test_triplet_default(self) -> None:
        m = ExampleBgrTripletRegister()
        assert m.bgr_triplet == (128.0, 128.0, 128.0)


class TestCompoundNumericAdapter:
    def test_binding(self) -> None:
        b = compound_numeric_binding()
        assert b.register_name == ExampleBgrTripletRegister.BINDING_REGISTER

    def test_numeric_view_slider(self) -> None:
        vc = compound_numeric_view_config_from_ui(
            ExampleCompoundNumericUiConfig(numeric_view_type="slider", show_ticks=True)
        )
        assert vc.view_type == "slider"
        assert vc.show_ticks is True


class TestCreateExampleCompoundNumeric:
    def test_create_smoke(self, qapp) -> None:
        r = create_example_compound_numeric(
            None,
            ExampleCompoundNumericUiConfig(label_b="B"),
        )
        assert r.widget is not None
        assert len(r.results) == 3


class TestCompoundMixedSchemas:
    def test_defaults(self) -> None:
        assert ExampleMixedBoolRegister().mix_enabled is False
        assert ExampleMixedFloatRegister().mix_level == 50.0


class TestCreateExampleCompoundMixed:
    def test_create_smoke(self, qapp) -> None:
        r = create_example_compound_mixed(
            None,
            ExampleCompoundMixedUiConfig(mix_checkbox_label="On"),
        )
        assert r.widget is not None
        assert len(r.results) == 2


class TestLabelSchemas:
    def test_label_config(self) -> None:
        cfg = label_config_from_ui(ExampleLabelUiConfig(label_text="  Hi  "))
        assert cfg.label == "Hi"


class TestCreateExampleLabel:
    def test_create_smoke(self, qapp) -> None:
        r = create_example_label(ExampleLabelUiConfig(label_text="T"))
        assert r.widget is not None


class TestNumericSchemas:
    def test_register_default(self) -> None:
        assert ExampleNumericValueRegister().demo_scalar == 33.0

    def test_ui_view_type(self) -> None:
        u = ExampleNumericUiConfig(numeric_view_type="spinbox")
        assert u.numeric_view_type == "spinbox"


class TestNumericAdapter:
    def test_binding(self) -> None:
        b = numeric_binding()
        assert b.field_name == ExampleNumericValueRegister.BINDING_FIELD

    def test_view_config_spinbox(self) -> None:
        vc = numeric_view_config_from_ui(
            ExampleNumericUiConfig(numeric_view_type="spinbox", numeric_label="  x  ")
        )
        assert vc.view_type == "spinbox"
        assert vc.label == "x"


class TestCreateExampleNumeric:
    def test_create_smoke(self, qapp) -> None:
        r = create_example_numeric(
            None,
            ExampleNumericUiConfig(numeric_label="N", numeric_view_type="slider"),
        )
        assert r.widget is not None
        assert r.presenter is not None


class TestGroupRow:
    def test_coerce_dict(self) -> None:
        u = group_row_coerce_ui({"row_label": "A", "view_type": "spinbox"})
        assert u.row_label == "A"
        assert u.view_type == "spinbox"

    def test_create_smoke(self, qapp) -> None:
        r = create_example_group_row(ExampleGroupRowUiConfig(row_label="R"))
        assert r.widget is not None
