# -*- coding: utf-8 -*-
"""Регистр без ``apply_values`` (не ``SchemaBase``): ``set_field_value`` возвращает кортеж, не бросает.

Находка ревью 1b.2d-2, ит.1: менеджер принимает любые регистры (``set_register(name, instance: Any)``,
в прототипе — ``_RawRegisterData(BaseModel)``), а запись через ``reg.apply_values`` роняла
``AttributeError`` наружу. Контракт метода — ``(bool, str | None)``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from multiprocess_framework.modules.registers_module.core.manager import RegistersManager


class _Raw(BaseModel):
    """Как ``_RawRegisterData`` прототипа: голый BaseModel без SchemaMixin."""

    model_config = ConfigDict(validate_assignment=True)
    data: dict[str, Any] = {}
    count: int = 0


def test_non_schema_register_write_passes() -> None:
    rm = RegistersManager(registers={"cam": _Raw(data={"a": 1})})
    assert rm.set_field_value("cam", "data", {"a": 2}) == (True, None)
    assert rm.get_register("cam").data == {"a": 2}


def test_non_schema_register_refusal_is_a_tuple_without_the_input() -> None:
    rm = RegistersManager(registers={"cam": _Raw()})
    marker = "SECRET-91c2"
    ok, err = rm.set_field_value("cam", "count", marker)
    assert ok is False
    assert err and marker not in err
    assert rm.get_register("cam").count == 0
