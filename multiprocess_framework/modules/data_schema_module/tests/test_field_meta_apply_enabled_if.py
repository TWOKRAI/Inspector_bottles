# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 1.1 (слепые): ``FieldMeta.apply`` и ``FieldMeta.enabled_if``.

Источник — ACCEPTANCE задачи ``plans/2026-10-18_camera-device-service/tasks/1.1.md``.
Ожидаемые значения — литералы оттуда, не вычисляются из кода под тестом.

Схемы-примеры собирает ``_build_schemas()`` (вызов в теле теста, вне ``pytest.raises``),
а не уровень модуля: до реализации ``FieldMeta(..., enabled_if=...)`` бросает ``TypeError``
прямо в теле класса, и модуль-уровень превратил бы красные тесты в ошибку сбора.
Файл намеренно БЕЗ ``from __future__ import annotations``: аннотации в теле локального
класса вычисляются сразу, локальные имена разрешать не нужно.
Определение схемы идёт вне ``pytest.raises`` — оно само по себе не должно падать.
"""

import json
from types import SimpleNamespace
from typing import Annotated, Any

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

_LEGACY_KEYS = {
    "description",
    "info",
    "unit",
    "min",
    "max",
    "transfer_k",
    "round_k",
    "routing",
    "access_level",
    "readonly",
    "hidden",
    "examples",
    "widget",
    "ui_group",
    "ui_order",
    "ui_hidden",
    "rules",
}


def _build_schemas() -> SimpleNamespace:
    """Свежие классы на каждый вызов (кэш ``get_all_fields_meta`` не переживает тест)."""

    class BadRef(SchemaBase):
        gain: Annotated[float, FieldMeta("g", enabled_if={"no_such": [1]})] = 0.0

    class PlainRef(SchemaBase):
        trigger_managed: bool = False
        gain: Annotated[float, FieldMeta("g", enabled_if={"trigger_managed": [True]})] = 0.0

    class SelfRef(SchemaBase):
        gain: Annotated[float, FieldMeta("g", enabled_if={"gain": [1]})] = 0.0

    class Parent(SchemaBase):
        flag: bool = False

    class Child(Parent):
        v: Annotated[int, FieldMeta("v", enabled_if={"flag": [True]})] = 0

    return SimpleNamespace(BadRef=BadRef, PlainRef=PlainRef, SelfRef=SelfRef, Parent=Parent, Child=Child)


# ---------------------------------------------------------------------------
# ACCEPTANCE 1: to_dict
# ---------------------------------------------------------------------------


def test_apply_is_written_to_dict() -> None:
    assert FieldMeta(apply="restart").to_dict()["apply"] == "restart"


def test_to_dict_of_plain_meta_has_exactly_the_17_legacy_keys() -> None:
    """Нет ``apply`` и ``enabled_if`` у поля, где они не заданы (охранный тест: красный
    только под инъекцией «to_dict всегда пишет apply: None»)."""
    assert set(FieldMeta("x").to_dict()) == _LEGACY_KEYS


# ---------------------------------------------------------------------------
# ACCEPTANCE 2: конструктор строг, from_dict мягок
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "must_contain", "must_not_contain"),
    [
        ({"apply": "later"}, "later", None),
        ({"apply": ["x"]}, None, None),
        ({"enabled_if": {"mode": "auto"}}, "mode", "auto"),
        ({"enabled_if": {"mode": []}}, None, None),
    ],
    ids=["apply-unknown-mode", "apply-list-not-str", "enabled_if-str-instead-of-list", "enabled_if-empty-list"],
)
def test_constructor_rejects_invalid_apply_and_enabled_if_with_value_error(
    kwargs: dict[str, Any], must_contain: str | None, must_not_contain: str | None
) -> None:
    """``ValueError`` (не ``TypeError``: тот пройдёт мимо ``pytest.raises(ValueError)``)."""
    with pytest.raises(ValueError) as exc_info:
        FieldMeta("x", **kwargs)
    if must_contain is not None:
        assert must_contain in str(exc_info.value)
    if must_not_contain is not None:
        assert must_not_contain not in str(exc_info.value)  # значение в текст не попадает


@pytest.mark.parametrize(
    ("payload", "attr"),
    [
        ({"apply": "later"}, "apply"),
        ({"enabled_if": {"mode": "auto"}}, "enabled_if"),
        ({"description": "x"}, "apply"),
        ({"description": "x"}, "enabled_if"),
    ],
    ids=["bad-apply-dropped", "bad-enabled_if-dropped", "legacy-dict-apply-none", "legacy-dict-enabled_if-none"],
)
def test_from_dict_gives_none_for_invalid_or_absent_keys(payload: dict[str, Any], attr: str) -> None:
    assert getattr(FieldMeta.from_dict(payload), attr) is None


# ---------------------------------------------------------------------------
# ACCEPTANCE 3: round-trip через JSON и копия
# ---------------------------------------------------------------------------


def test_enabled_if_survives_json_round_trip() -> None:
    m = FieldMeta(enabled_if={"trigger_managed": [True]})
    restored = FieldMeta.from_dict(json.loads(json.dumps(m.to_dict())))
    assert restored.enabled_if == {"trigger_managed": [True]}


def test_to_dict_enabled_if_is_a_copy_not_the_stored_object() -> None:
    m = FieldMeta(enabled_if={"trigger_managed": [True]})
    assert m.to_dict()["enabled_if"] is not m.enabled_if


# ---------------------------------------------------------------------------
# ACCEPTANCE 4: форма enabled_if
# ---------------------------------------------------------------------------


def test_empty_enabled_if_is_stored_as_none_and_not_serialised() -> None:
    m = FieldMeta(enabled_if={})
    assert m.enabled_if is None
    assert "enabled_if" not in m.to_dict()


# ---------------------------------------------------------------------------
# ACCEPTANCE 5: is_enabled (И по ключам, ИЛИ по значениям, сравнение ==)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled_if", "values", "expected"),
    [
        ({"trigger_managed": [True]}, {"trigger_managed": True}, True),
        ({"trigger_managed": [True]}, {"trigger_managed": False}, False),
        ({"trigger_managed": [True]}, {}, False),
        (None, {}, True),
        ({"x": [1]}, {"x": True}, True),
        ({"a": [1], "b": [2, 3]}, {"a": 1, "b": 3}, True),
        ({"a": [1], "b": [2, 3]}, {"a": 1, "b": 4}, False),
    ],
    ids=["match", "mismatch", "key-missing", "no-condition", "int-equals-bool", "and-or-hit", "and-or-miss"],
)
def test_is_enabled(enabled_if: dict[str, list[Any]] | None, values: dict[str, Any], expected: bool) -> None:
    assert FieldMeta(enabled_if=enabled_if).is_enabled(values) is expected


# ---------------------------------------------------------------------------
# ACCEPTANCE 6: проверка ссылок в get_all_fields_meta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "field_in_text"),
    [("BadRef", "no_such"), ("SelfRef", "gain")],
    ids=["missing-field", "self-reference"],
)
def test_get_all_fields_meta_raises_on_bad_enabled_if_reference_every_time(name: str, field_in_text: str) -> None:
    """Определение класса (фикстура) не падает; оба вызова бросают (кэш не отравлен)."""
    cls = getattr(_build_schemas(), name)
    with pytest.raises(ValueError) as first:
        cls.get_all_fields_meta()
    assert field_in_text in str(first.value)
    with pytest.raises(ValueError) as second:
        cls.get_all_fields_meta()
    assert field_in_text in str(second.value)


@pytest.mark.parametrize(
    ("name", "field", "expected"),
    [
        ("PlainRef", "gain", {"trigger_managed": [True]}),
        ("Child", "v", {"flag": [True]}),
    ],
    ids=["field-without-meta", "parent-field"],
)
def test_get_all_fields_meta_accepts_reference_to_plain_or_inherited_field(
    name: str, field: str, expected: dict[str, list[Any]]
) -> None:
    result = getattr(_build_schemas(), name).get_all_fields_meta()
    assert result[field].enabled_if == expected
