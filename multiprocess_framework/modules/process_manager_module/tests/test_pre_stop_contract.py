# -*- coding: utf-8 -*-
"""Контракт-тест ``process/pre_stop.py`` (Task 1.4 gui-graceful-close, lite-контракт, ADR-PMM-044).

Публичное API: ``PreStopStep``, ``parse_pre_stop``, ``PRE_STOP_STEP_MAX_S``, ``PRE_STOP_TOTAL_MAX_S``.
Ожидаемые значения — литералы из DESIGN 5 задачи, не выведены из кода.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from ..process import pre_stop as mod
from ..process.pre_stop import PRE_STOP_STEP_MAX_S, PRE_STOP_TOTAL_MAX_S, PreStopStep, parse_pre_stop


def _entry(timeout_s=5, **override):
    base = {"process": "arm", "command": "robot.home", "args": {"speed": 1}, "timeout_s": timeout_s}
    base.update(override)
    return base


def test_public_api_names_and_constants() -> None:
    assert sorted(mod.__all__) == ["PRE_STOP_STEP_MAX_S", "PRE_STOP_TOTAL_MAX_S", "PreStopStep", "parse_pre_stop"]
    assert PRE_STOP_STEP_MAX_S == 60.0
    assert PRE_STOP_TOTAL_MAX_S == 120.0


@pytest.mark.parametrize("raw", [None, []], ids=["none", "empty"])
def test_empty_is_no_steps_no_errors(raw) -> None:
    assert parse_pre_stop(raw) == ([], [])


@pytest.mark.parametrize("raw", [{"process": "a"}, "steps", 7], ids=["dict", "str", "int"])
def test_not_a_list_is_one_error(raw) -> None:
    assert parse_pre_stop(raw) == ([], ["pre_stop: ожидается список"])


def test_valid_step_fields_label_and_defaults() -> None:
    steps, errors = parse_pre_stop([_entry(5), {"process": "b", "command": "c", "timeout_s": 0.5}])
    assert errors == []
    assert [s.label for s in steps] == ["arm.robot.home", "b.c"]
    assert steps[0].timeout_s == 5.0 and isinstance(steps[0].timeout_s, float)
    assert steps[0].args == {"speed": 1}
    assert steps[1].args == {}


def test_step_is_frozen() -> None:
    step = PreStopStep(process="a", command="b", timeout_s=1)
    with pytest.raises(ValidationError):
        step.timeout_s = 2.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("value", "field"),
    [
        (0, "timeout_s"),
        (-1, "timeout_s"),
        (60.0001, "timeout_s"),
        (math.nan, "timeout_s"),
        (math.inf, "timeout_s"),
        (True, "timeout_s"),
        ("5", "timeout_s"),
    ],
    ids=["zero", "negative", "over-60", "nan", "inf", "bool", "string"],
)
def test_bad_timeout_skipped_with_field_error(value, field) -> None:
    steps, errors = parse_pre_stop([_entry(value), _entry(1)])
    assert [s.timeout_s for s in steps] == [1.0]
    assert len(errors) == 1
    assert errors[0].startswith(f"pre_stop[0]: {field} — ")


def test_boundary_60_accepted() -> None:
    steps, errors = parse_pre_stop([_entry(60)])
    assert (len(steps), errors) == (1, [])


@pytest.mark.parametrize(
    ("override", "prefix"),
    [
        ({"process": ""}, "pre_stop[0]: process — "),
        ({"command": ""}, "pre_stop[0]: command — "),
        ({"process": 5}, "pre_stop[0]: process — "),
        ({"args": [1]}, "pre_stop[0]: args — "),
    ],
    ids=["empty-process", "empty-command", "int-process", "list-args"],
)
def test_bad_field_names_field(override, prefix) -> None:
    steps, errors = parse_pre_stop([_entry(5, **override)])
    assert steps == []
    assert len(errors) == 1 and errors[0].startswith(prefix), errors


def test_extra_key_reported_without_its_name() -> None:
    steps, errors = parse_pre_stop([_entry(5, secret_key_zz="value_zz")])
    assert steps == []
    assert errors == ["pre_stop[0]: поле — неизвестный ключ"]


def test_non_dict_record() -> None:
    steps, errors = parse_pre_stop([7, _entry(1)])
    assert len(steps) == 1
    assert errors == ["pre_stop[0]: запись — ожидается объект"]


def test_several_errors_of_one_record_in_one_line_without_input_values() -> None:
    raw = [{"process": "", "command": "", "timeout_s": "SECRET_TIMEOUT", "zz_extra": "SECRET_EXTRA", "args": {9: 1}}]
    steps, errors = parse_pre_stop(raw)
    assert steps == []
    assert len(errors) == 1
    text = errors[0]
    assert text.startswith("pre_stop[0]: ")
    for banned in ("SECRET_TIMEOUT", "SECRET_EXTRA", "zz_extra", "9"):
        assert banned not in text, text


def test_total_ceiling_skips_overflowing_record_and_keeps_later_fitting() -> None:
    steps, errors = parse_pre_stop([_entry(60), _entry(50), _entry(20), _entry(10)])
    assert [s.timeout_s for s in steps] == [60.0, 50.0, 10.0]
    assert errors == ["pre_stop[2]: timeout_s — сумма шагов больше 120 с"]


def test_total_ceiling_counts_only_accepted_records() -> None:
    # Негодная запись [0] в сумму не входит: 60 + 60 == 120 — граница включительно.
    steps, errors = parse_pre_stop([_entry(0), _entry(60), _entry(60)])
    assert [s.timeout_s for s in steps] == [60.0, 60.0]
    assert len(errors) == 1 and errors[0].startswith("pre_stop[0]: timeout_s — ")


def test_total_float_sum_at_boundary_is_not_overflow() -> None:
    steps, errors = parse_pre_stop([_entry(0.1)] * 1200)
    assert (len(steps), errors) == (1200, [])
