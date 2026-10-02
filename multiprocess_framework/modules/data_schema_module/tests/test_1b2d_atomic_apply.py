# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.2d (б): ``SchemaMixin.update_field`` — отказ = ничего не записано.

Решение владельца (2026-10-02): отвергнутое значение не остаётся в регистре. Раньше на
``SchemaBase`` с ``model_validator(mode="after")`` измерено: ``validate_assignment`` ставит
значение, затем after-валидатор бросает — значение остаётся, а ``update_field`` возвращает
``(False, err)``. Тест на маленьком классе, связывающем два поля (``lo <= hi``), проверяет
ТОЛЬКО наблюдаемое: ``(False, err)``, значение и ``model_fields_set`` не изменились.
Механизм отката не предполагается.
"""

from __future__ import annotations

from pydantic import model_validator

from multiprocess_framework.modules.data_schema_module import SchemaBase


class _Pair(SchemaBase):
    """Два связанных поля: инвариант ``lo <= hi`` проверяется ПОСЛЕ присваивания."""

    lo: int = 1
    hi: int = 10

    @model_validator(mode="after")
    def _lo_le_hi(self) -> "_Pair":
        if self.lo > self.hi:
            raise ValueError(f"lo ({self.lo}) must be <= hi ({self.hi})")
        return self


def _pair() -> _Pair:
    # hi задан явно -> model_fields_set == {"hi"}: «не изменился» отличим от «пересоздан с нуля»
    return _Pair(hi=10)


def test_update_field_rejects_lo_above_hi_and_writes_nothing() -> None:
    """Post: ``lo = 50`` при ``hi = 10`` -> ``(False, непустая ошибка)``; lo == 1, fields_set == {"hi"}."""
    reg = _pair()
    ok, err = reg.update_field("lo", 50)
    assert ok is False
    assert err, "текст ошибки пуст"
    assert reg.lo == 1, f"отвергнутое значение осталось в поле: lo={reg.lo}"
    assert reg.hi == 10
    assert reg.model_fields_set == {"hi"}, f"model_fields_set изменился: {reg.model_fields_set}"


def test_update_field_rejects_hi_below_lo_and_writes_nothing() -> None:
    """Post: ``hi = 0`` при ``lo = 1`` -> ``(False, ...)``; hi == 10, fields_set == {"hi"}."""
    reg = _pair()
    ok, err = reg.update_field("hi", 0)
    assert ok is False
    assert err
    assert reg.hi == 10, f"отвергнутое значение осталось в поле: hi={reg.hi}"
    assert reg.lo == 1
    assert reg.model_fields_set == {"hi"}, f"model_fields_set изменился: {reg.model_fields_set}"


def test_update_field_accepts_valid_value_control() -> None:
    """Контроль (зелёный сегодня): ``lo = 5`` принято, записано, поле отмечено как заданное."""
    reg = _pair()
    ok, err = reg.update_field("lo", 5)
    assert (ok, err) == (True, None)
    assert reg.lo == 5
    assert reg.model_fields_set == {"lo", "hi"}


def test_update_field_accepts_boundary_lo_equal_hi_control() -> None:
    """Контроль границы (зелёный сегодня): ``lo = 10`` при ``hi = 10`` разрешено."""
    reg = _pair()
    ok, err = reg.update_field("lo", 10)
    assert (ok, err) == (True, None)
    assert reg.lo == 10
