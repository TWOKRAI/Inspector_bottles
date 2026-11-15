# -*- coding: utf-8 -*-
"""Приёмочные тесты `params.py` (Task 1.6): план записи профиля из register'а и таблицы привязки.

Файл БЕЗ `from __future__ import annotations`: аннотации локального register-класса должны быть
настоящими объектами (`Annotated[..., FieldMeta]`), а не строками (как в тестах ADR-DS-011).
Ожидаемые значения — литералы из ACCEPTANCE задачи, не вычисляются из кода под тестом.
Тестовый register определён здесь: `registers_base.py` — Task 1.8.
"""

from typing import Annotated

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from Services.camera_device.interface import Binding
from Services.camera_device.params import Step, build_plan, check_bindings


class TriggerRegister(SchemaBase):
    """Группа триггера: флаг `trigger_managed` + три поля, зависящие друг от друга."""

    trigger_managed: Annotated[bool, FieldMeta("управлять триггером", ui_group="trigger")] = False
    trigger_mode: Annotated[
        str,
        FieldMeta("режим", ui_group="trigger", enabled_if={"trigger_managed": [True]}),
    ] = "Off"
    trigger_source: Annotated[
        str,
        FieldMeta("источник", ui_group="trigger", enabled_if={"trigger_managed": [True], "trigger_mode": ["On"]}),
    ] = "Line0"
    trigger_period_ms: Annotated[
        int,
        FieldMeta(
            "период",
            ui_group="trigger",
            enabled_if={"trigger_managed": [True], "trigger_source": ["SelfTrigger"]},
        ),
    ] = 40


BINDINGS = {
    "trigger_mode": Binding("genicam", "TriggerMode", "enum"),
    "trigger_source": Binding("genicam", "TriggerSource", "enum"),
    "trigger_period_ms": Binding("genicam", "TriggerSelfTriggerPeriod", "int"),
}


def _applied(plan: list[Step]) -> list[tuple[str, object]]:
    """Что реально будет записано: пары (имя узла, значение) шагов без пропуска."""
    return [(s.binding.key, s.value) for s in plan if s.skip is None]


def test_план_selftrigger():
    values = {"trigger_managed": True, "trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 40}
    plan = build_plan(TriggerRegister, values, BINDINGS)
    assert [(s.binding.key, s.value) for s in plan] == [
        ("TriggerMode", "On"),
        ("TriggerSource", "SelfTrigger"),
        ("TriggerSelfTriggerPeriod", 40),
    ]
    assert all(s.skip is None for s in plan)


def test_план_line0_пропуск_периода():
    values = {"trigger_managed": True, "trigger_mode": "On", "trigger_source": "Line0", "trigger_period_ms": 40}
    plan = build_plan(TriggerRegister, values, BINDINGS)
    assert _applied(plan) == [("TriggerMode", "On"), ("TriggerSource", "Line0")]
    assert len(plan) == 3
    period = plan[2]
    assert period.field == "trigger_period_ms"
    assert period.skip == "не нужен: trigger_source=Line0"


def test_план_off():
    plan = build_plan(TriggerRegister, {"trigger_managed": True, "trigger_mode": "Off"}, BINDINGS)
    assert _applied(plan) == [("TriggerMode", "Off")]
    assert [s.skip is not None for s in plan] == [False, True, True]
    assert plan[1].skip == "не нужен: trigger_mode=Off"


def test_группа_не_управляется():
    plan = build_plan(TriggerRegister, {"trigger_managed": False, "trigger_mode": "On"}, BINDINGS)
    assert plan == []


def test_лишний_ключ_привязки():
    # eps_abs=40.0: repr такой привязки в тексте ошибки принёс бы «40» (значение из рецепта) — тест это ловит.
    bad = dict(BINDINGS)
    bad["trigger_periodms"] = Binding("genicam", "TriggerSelfTriggerPeriod", "int", eps_abs=40.0)
    with pytest.raises(ValueError) as exc_info:
        check_bindings(TriggerRegister, bad, vendor_fields=())
    text = str(exc_info.value)
    assert "trigger_periodms" in text
    assert "40" not in text


def test_недостающий_ключ_привязки():
    incomplete = {k: v for k, v in BINDINGS.items() if k != "trigger_period_ms"}
    with pytest.raises(ValueError) as exc_info:
        check_bindings(TriggerRegister, incomplete, vendor_fields=())
    assert "trigger_period_ms" in str(exc_info.value)


def test_полная_таблица_проходит_проверку():
    # Флаг `trigger_managed` привязки не имеет: это переключатель группы, а не параметр прибора.
    check_bindings(TriggerRegister, BINDINGS, vendor_fields=())


def test_порядок_шагов_порядок_полей_класса():
    values = {"trigger_managed": True, "trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 40}
    plan = build_plan(TriggerRegister, values, BINDINGS)
    assert [s.field for s in plan] == ["trigger_mode", "trigger_source", "trigger_period_ms"]
