"""Тесты ControlSpec — дефолт-значения, коэрция по типу, парсинг list[dict]."""

from __future__ import annotations

import pytest

from Services.control_panel.controls import ControlSpec, controls_to_dicts, parse_controls


class TestDefaultValue:
    def test_button_default_is_trigger(self) -> None:
        assert ControlSpec(id="b", type="button", trigger_value=1).default_value() == 1

    def test_toggle_default_false(self) -> None:
        assert ControlSpec(id="t", type="toggle").default_value() is False

    def test_slider_default_min(self) -> None:
        assert ControlSpec(id="s", type="slider", min=5.0, max=10.0).default_value() == 5.0

    def test_text_default_empty(self) -> None:
        assert ControlSpec(id="x", type="text").default_value() == ""


class TestCoerce:
    def test_toggle_coerces_bool(self) -> None:
        spec = ControlSpec(id="t", type="toggle")
        assert spec.coerce(1) is True
        assert spec.coerce(0) is False

    def test_number_clamps_to_range(self) -> None:
        spec = ControlSpec(id="n", type="number", min=0.0, max=100.0)
        assert spec.coerce(150) == 100.0
        assert spec.coerce(-5) == 0.0
        assert spec.coerce(42) == 42.0

    def test_number_invalid_falls_to_min(self) -> None:
        spec = ControlSpec(id="n", type="number", min=3.0, max=9.0)
        assert spec.coerce("abc") == 3.0

    def test_button_always_trigger(self) -> None:
        spec = ControlSpec(id="b", type="button", trigger_value="GO")
        assert spec.coerce(123) == "GO"

    def test_text_stringifies(self) -> None:
        spec = ControlSpec(id="x", type="text")
        assert spec.coerce(42) == "42"
        assert spec.coerce(None) == ""


class TestSelect:
    """select — выпадающий список: дефолт = первый пункт, coerce валидирует value."""

    def _spec(self) -> ControlSpec:
        return ControlSpec(
            id="mode",
            type="select",
            options=[
                {"label": "Рисование", "value": "draw"},
                {"label": "Ручной", "value": "manual"},
                {"label": "Конвейер", "value": "cvt"},
            ],
        )

    def test_default_is_first_option(self) -> None:
        assert self._spec().default_value() == "draw"

    def test_default_empty_when_no_options(self) -> None:
        assert ControlSpec(id="s", type="select").default_value() == ""

    def test_coerce_keeps_valid_value(self) -> None:
        assert self._spec().coerce("manual") == "manual"

    def test_coerce_falls_to_first_when_invalid(self) -> None:
        assert self._spec().coerce("fly") == "draw"

    def test_option_values_listed(self) -> None:
        assert self._spec().option_values() == ["draw", "manual", "cvt"]

    def test_roundtrip_keeps_options(self) -> None:
        specs = parse_controls(controls_to_dicts([self._spec()]))
        assert specs[0].type == "select"
        assert specs[0].option_values() == ["draw", "manual", "cvt"]


class TestParseControls:
    def test_parse_fills_default_value(self) -> None:
        specs = parse_controls([{"id": "s", "type": "slider", "min": 2.0, "max": 8.0}])
        assert len(specs) == 1
        assert specs[0].value == 2.0  # default = min

    def test_parse_skips_broken_and_dups(self) -> None:
        specs = parse_controls(
            [
                {"id": "a", "type": "button"},
                {"id": "a", "type": "toggle"},  # дубль id — отброшен
                {"no_id": True},  # битая запись — пропущена
                "not a dict",  # пропущена
                {"id": "b", "type": "text"},
            ]
        )
        assert [s.id for s in specs] == ["a", "b"]

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(Exception):
            ControlSpec(id="  ", type="button")

    def test_roundtrip_dicts(self) -> None:
        specs = parse_controls([{"id": "a", "type": "toggle", "port": "out_3"}])
        dicts = controls_to_dicts(specs)
        assert dicts[0]["id"] == "a"
        assert dicts[0]["port"] == "out_3"
        # повторный парсинг даёт эквивалент
        assert parse_controls(dicts)[0].port == "out_3"


class TestDashboardSource:
    """Phase 5: source-режимы (local/param/monitor/action) + target-адресация."""

    def test_default_source_local(self) -> None:
        assert ControlSpec(id="a", type="button").source == "local"

    def test_param_targets_other_node(self) -> None:
        spec = ControlSpec(
            id="thr",
            type="slider",
            source="param",
            target_process="seg",
            target_field="threshold",
            min=0.0,
            max=1.0,
        )
        assert spec.source == "param"
        assert spec.target_process == "seg"
        assert spec.target_field == "threshold"
        # coerce по-прежнему по ВИДУ виджета (type), source ортогонален
        assert spec.coerce(2.0) == 1.0  # slider clamp

    def test_action_targets_command(self) -> None:
        spec = ControlSpec(
            id="draw", type="button", source="action", target_process="points", target_command="robot_draw_send"
        )
        assert spec.source == "action"
        assert spec.target_command == "robot_draw_send"

    def test_roundtrip_preserves_dashboard_fields(self) -> None:
        raw = [
            {
                "id": "thr",
                "type": "number",
                "source": "param",
                "target_process": "seg",
                "target_plugin_index": 0,
                "target_field": "threshold",
            }
        ]
        specs = parse_controls(raw)
        out = controls_to_dicts(specs)[0]
        assert out["source"] == "param"
        assert out["target_process"] == "seg"
        assert out["target_field"] == "threshold"
