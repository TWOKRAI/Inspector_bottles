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
