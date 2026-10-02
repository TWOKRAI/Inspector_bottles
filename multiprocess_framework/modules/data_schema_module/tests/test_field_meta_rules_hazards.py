# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1b.2d-2: правила FieldMeta данными + атомарная запись (ADR-DS-010).

Что может сломаться в ЭТОМ механизме, исходя из того, как он построен:

* правило живёт в ``FieldMeta`` и переезжает через ``to_dict``/``from_dict`` — потерянный ключ
  при round-trip молча делает копию регистра мягче оригинала;
* поле без правил обязано получать схему pydantic БЕЗ обёртки — иначе цену платят все 130
  наследников ``SchemaBase`` на каждом присваивании;
* строковое правило на нестроковом входе не должно ронять ``AttributeError`` наружу;
* ``apply_values`` откатывает и ``__dict__``, и ``__pydantic_fields_set__``; pydantic-core на
  ``validate_assignment`` ЗАМЕНЯЕТ объект ``__dict__`` — откат по ссылке, взятой до записи,
  был бы пустым;
* переобъявленное в подклассе поле получает СВОЙ ``FieldMeta`` и теряет правила родителя —
  ловушка, на которой стоял ``OtelExportRegisters.endpoint``.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

import pytest
from pydantic import ValidationError, model_validator

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_framework.modules.registers_module.core.manager import RegistersManager

_RULES = {
    "strip": True,
    "pattern": r"[a-z]+",
    "pattern_message": "только строчные латинские",
    "le_field": "hi",
}


def _walk_types(schema: Any) -> list[str]:
    """Все значения ключа ``type`` в дереве core-схемы (порядок обхода не важен)."""
    found: list[str] = []
    if isinstance(schema, dict):
        if isinstance(schema.get("type"), str):
            found.append(schema["type"])
        for value in schema.values():
            found += _walk_types(value)
    elif isinstance(schema, list):
        for value in schema:
            found += _walk_types(value)
    return found


# ---------------------------------------------------------------------------
# Описание правил: round-trip и словарь
# ---------------------------------------------------------------------------


def test_rules_round_trip_through_dict_and_json() -> None:
    """``to_dict -> json -> from_dict`` возвращает те же правила (литерал, а не производная)."""
    meta = FieldMeta("x", rules=dict(_RULES, choices_map={"WARN": "WARNING"}))
    wire = json.loads(json.dumps(meta.to_dict()))
    back = FieldMeta.from_dict(wire)
    assert back.rules == {
        "strip": True,
        "pattern": "[a-z]+",
        "pattern_message": "только строчные латинские",
        "le_field": "hi",
        "choices_map": {"WARN": "WARNING"},
    }


def test_to_dict_rules_is_a_copy_not_the_class_dict() -> None:
    """Мутация выданного описания не меняет правила класса (получатель не правит оригинал)."""
    meta = FieldMeta("x", rules={"choices_map": {"A": "A"}})
    out = meta.to_dict()
    out["rules"]["choices_map"]["B"] = "B"
    assert meta.rules == {"choices_map": {"A": "A"}}


def test_unknown_rule_key_in_constructor_raises() -> None:
    with pytest.raises(ValueError, match="ge_field"):
        FieldMeta("x", rules={"ge_field": "lo"})


def test_unknown_rule_key_in_from_dict_is_dropped_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """GUI старше хаба: незнакомое правило отброшено со строкой в журнал, остальное цело."""
    with caplog.at_level(logging.WARNING):
        back = FieldMeta.from_dict({"description": "x", "rules": {"strip": True, "future_rule": 1}})
    assert back.rules == {"strip": True}
    assert "future_rule" in caplog.text


# ---------------------------------------------------------------------------
# Цена: поле без правил не обёрнуто
# ---------------------------------------------------------------------------


def test_rule_less_field_schema_has_no_after_validator_and_rules_field_has_one() -> None:
    """Поле без rules — схема без function-after; поле с правилом уровня поля — с ней (контроль)."""

    class _Plain(SchemaBase):
        a: Annotated[str, FieldMeta("a", min=0)] = ""

    class _Ruled(SchemaBase):
        a: Annotated[str, FieldMeta("a", rules={"strip": True})] = ""

    class _OnlyLe(SchemaBase):
        a: Annotated[int, FieldMeta("a", rules={"le_field": "b"})] = 0
        b: int = 1

    assert "function-after" not in _walk_types(_Plain.__pydantic_core_schema__["schema"]["schema"])
    assert "function-after" in _walk_types(_Ruled.__pydantic_core_schema__["schema"]["schema"])
    # le_field — межполевое, исполняется в _check_field_constraints: обёртки поля нет
    assert "function-after" not in _walk_types(_OnlyLe.__pydantic_core_schema__["schema"]["schema"])


# ---------------------------------------------------------------------------
# Исполнение правил
# ---------------------------------------------------------------------------


class _AnyRuled(SchemaBase):
    s: Annotated[Any, FieldMeta("s", rules={"strip": True, "pattern": r"[a-z]+"})] = "a"
    m: Annotated[Any, FieldMeta("m", rules={"value_pattern": r"\d+"})] = {}
    c: Annotated[Any, FieldMeta("c", rules={"choices_map": {"WARN": "WARNING", "INFO": "INFO"}})] = "INFO"


@pytest.mark.parametrize(("field", "value"), [("s", 5), ("c", 5), ("m", [1]), ("m", {"k": 5})])
def test_non_string_input_to_string_rule_is_validation_error(field: str, value: Any) -> None:
    """Нестроковый вход в строковое правило → ValidationError, никогда AttributeError."""
    reg = _AnyRuled()
    with pytest.raises(ValidationError):
        setattr(reg, field, value)


def test_choices_map_uses_upper_not_casefold() -> None:
    """``"ınfo".upper() == "INFO"`` (точечная i) — поиск по upper, как у normalize_level_name."""
    reg = _AnyRuled()
    assert reg.apply_values({"c": "ınfo"}) == (True, None)
    assert reg.c == "INFO"
    assert reg.apply_values({"c": "warn"}) == (True, None)
    assert reg.c == "WARNING"


def test_le_field_none_on_either_side_is_skipped() -> None:
    class _Opt(SchemaBase):
        a: Annotated[int | None, FieldMeta("a", rules={"le_field": "b"})] = None
        b: int | None = None

    reg = _Opt()
    assert reg.apply_values({"a": 100}) == (True, None)  # b is None
    assert reg.apply_values({"a": None, "b": 1}) == (True, None)  # a is None
    ok, err = reg.apply_values({"a": 2})
    assert ok is False and "'a'" in err and "'b'" in err


def test_redeclared_field_without_rules_loses_parent_rules() -> None:
    """ЛОВУШКА (фиксируется, а не обходится): переобъявление поля в подклассе стирает FieldMeta
    родителя вместе с его rules. Поэтому OtelExportRegisters передаёт ENDPOINT_RULES явно
    (реальный класс сторожат AC2-случаи endpoint в adapters/tests/test_1b2d_copy_agrees_with_original.py;
    импорт Plugins/Services отсюда запрещён слоями)."""

    class _Parent(SchemaBase):
        e: Annotated[str, FieldMeta("e", rules={"pattern": "a+"})] = "a"

    class _Child(_Parent):
        e: Annotated[str, FieldMeta("e")] = ""

    assert _Parent().apply_values({"e": "b"})[0] is False
    assert _Child().apply_values({"e": "b"}) == (True, None)


# ---------------------------------------------------------------------------
# apply_values: откат и текст отказа
# ---------------------------------------------------------------------------


class _Pair(SchemaBase):
    lo: int = 1
    hi: int = 10
    tag: str = ""

    @model_validator(mode="after")
    def _lo_le_hi(self) -> "_Pair":
        if self.lo > self.hi:
            raise ValueError("lo must be <= hi")
        return self


def test_rollback_restores_earlier_keys_and_fields_set() -> None:
    """Первый ключ принят, второй отвергнут → первый откатан, fields_set прежний (без 'tag')."""
    reg = _Pair(hi=10)
    ok, _ = reg.apply_values({"tag": "new", "lo": 50})
    assert ok is False
    assert (reg.tag, reg.lo, reg.hi) == ("", 1, 10)
    assert reg.model_fields_set == {"hi"}


def test_rollback_survives_pydantic_replacing_dict_object() -> None:
    """pydantic-core заменяет объект __dict__ на validate_assignment — откат пишет в ТЕКУЩИЙ."""
    reg = _Pair()
    before_id = id(reg.__dict__)
    reg.apply_values({"lo": 2})
    replaced = id(reg.__dict__) != before_id
    ok, _ = reg.apply_values({"lo": 99})
    assert ok is False and reg.lo == 2
    # Наблюдение, ради которого откат перечитывает __dict__ (если pydantic перестанет
    # заменять объект — тест скажет об этом, а не молча станет вакуумным).
    assert replaced, "pydantic больше не заменяет __dict__ на присваивании — пересмотреть комментарий отката"


def test_refusal_text_never_contains_input_value() -> None:
    """Ни тип, ни после-валидатор: введённое значение не попадает в текст (класс без hide_input)."""
    reg = _Pair()
    marker = "SECRET-7f3a9c"
    ok, err = reg.apply_values({"lo": marker})
    assert ok is False and marker not in err and err.startswith("lo:")
    ok, err = _AnyRuled().apply_values({"s": marker})
    assert ok is False and marker not in err


def test_reentrant_apply_inside_setattr_does_not_break_outer_rollback() -> None:
    """Вложенный apply_values изнутри setattr (переопределённый __setattr__) — внешний откат
    восстанавливает СВОИ ключи и свой fields_set.

    ПОТОЛОК (фиксируется литералом): ключ, записанный вложенным вызовом и не входящий во
    внешний набор, НЕ откатывается — снимок внешнего вызова его не видел. При этом fields_set
    возвращается к внешнему снимку, т.е. 'tag' хранит новое значение, но не отмечен заданным.
    """

    class _Nested(_Pair):
        def __setattr__(self, name: str, value: Any) -> None:
            super().__setattr__(name, value)
            if name == "hi":
                assert self.apply_values({"tag": "nested"}) == (True, None)

    reg = _Nested()
    ok, _ = reg.apply_values({"hi": 20, "lo": 50})
    assert ok is False
    assert (reg.lo, reg.hi) == (1, 10)
    assert reg.model_fields_set == set()
    assert reg.tag == "nested"  # потолок, см. docstring


# ---------------------------------------------------------------------------
# set_field_value: уведомление сохранённым значением
# ---------------------------------------------------------------------------


def test_set_field_value_notifies_stored_not_raw_value() -> None:
    class _Lvl(SchemaBase):
        level: Annotated[str, FieldMeta("level", rules={"choices_map": {"WARN": "WARNING"}})] = "WARNING"

    rm = RegistersManager(registers={"r": _Lvl()})
    seen_field: list[Any] = []
    seen_global: list[Any] = []
    rm.subscribe("r", "level", seen_field.append)
    rm.subscribe_all(lambda _reg, _field, value: seen_global.append(value))
    assert rm.set_field_value("r", "level", "warn") == (True, None)
    assert seen_field == ["WARNING"] and seen_global == ["WARNING"]
