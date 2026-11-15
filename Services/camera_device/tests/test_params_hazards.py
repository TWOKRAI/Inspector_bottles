# -*- coding: utf-8 -*-
"""Hazard-тесты `params.py` (Task 1.6, автор — исполнитель): то, что ACCEPTANCE не покрывает.

Файл БЕЗ `from __future__ import annotations` (локальные register-классы с `Annotated[..., FieldMeta]`).
Ожидаемые значения — литералы, не вычисляются из кода под тестом.
"""

from typing import Annotated

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from Services.camera_device.interface import Binding
from Services.camera_device.params import build_plan, check_bindings


class Base(SchemaBase):
    a: Annotated[int, FieldMeta("a")] = 1
    b: Annotated[int, FieldMeta("b")] = 2


class Child(Base):
    c: Annotated[int, FieldMeta("c")] = 3
    a: Annotated[int, FieldMeta("a, переобъявлено")] = 10  # переобъявленное поле держит позицию родителя


def _bindings(*names: str) -> dict[str, Binding]:
    return {n: Binding("genicam", n.upper(), "int") for n in names}


def test_порядок_при_наследовании_родитель_раньше_потомка():
    plan = build_plan(Child, {"a": 1, "b": 2, "c": 3}, _bindings("c", "b", "a"))
    # порядок словаря привязок обратный — порядок шагов задаёт класс
    assert [s.field for s in plan] == ["a", "b", "c"]


class Exposure(SchemaBase):
    exposure_managed: Annotated[bool, FieldMeta("управлять", ui_group="exposure")] = False
    gain: Annotated[float, FieldMeta("gain", ui_group="exposure", enabled_if={"exposure_managed": [True]})] = 1.0
    black_level: Annotated[
        int, FieldMeta("black level", ui_group="exposure", enabled_if={"exposure_managed": [True]})
    ] = 5
    label: Annotated[str, FieldMeta("подпись", ui_group="exposure", enabled_if={"exposure_managed": [True]})] = "x"
    free_gain: Annotated[float, FieldMeta("вне группы", ui_group="other")] = 2.0


EXPOSURE_BINDINGS = {
    "gain": Binding("genicam", "Gain", "float"),
    "black_level": Binding("genicam", "BlackLevel", "int"),
    "label": Binding("genicam", "DeviceUserID", "string"),
    "free_gain": Binding("genicam", "FreeGain", "float"),
}


def test_ноль_и_пустая_строка_это_значения():
    values = {"exposure_managed": True, "gain": 0.0, "black_level": 0, "label": "", "free_gain": 0}
    plan = build_plan(Exposure, values, EXPOSURE_BINDINGS)
    assert [(s.binding.key, s.value, s.skip) for s in plan] == [
        ("Gain", 0.0, None),
        ("BlackLevel", 0, None),
        ("DeviceUserID", "", None),
        ("FreeGain", 0, None),
    ]


def test_флаг_группы_false_снимает_группу_но_не_чужие_поля():
    values = {"exposure_managed": False, "gain": 3.0, "black_level": 4, "label": "q", "free_gain": 7}
    plan = build_plan(Exposure, values, EXPOSURE_BINDINGS)
    assert [(s.binding.key, s.value, s.skip) for s in plan] == [("FreeGain", 7, None)]


def test_флаг_группы_не_задан_значит_не_управлять():
    plan = build_plan(Exposure, {"gain": 3.0, "free_gain": 7}, EXPOSURE_BINDINGS)
    assert [s.binding.key for s in plan] == ["FreeGain"]


def test_ложный_enabled_if_у_родителя_снимает_и_потомка():
    class Chain(SchemaBase):
        mode: Annotated[str, FieldMeta("m")] = "Off"
        source: Annotated[str, FieldMeta("s", enabled_if={"mode": ["On"]})] = "Line0"
        period: Annotated[int, FieldMeta("p", enabled_if={"source": ["SelfTrigger"]})] = 40

    bindings = {
        "mode": Binding("genicam", "TriggerMode", "enum"),
        "source": Binding("genicam", "TriggerSource", "enum"),
        "period": Binding("genicam", "TriggerSelfTriggerPeriod", "int"),
    }
    # у потомка условие по значению родителя выполнено (SelfTrigger), но родитель сам не нужен при mode=Off
    plan = build_plan(Chain, {"mode": "Off", "source": "SelfTrigger", "period": 40}, bindings)
    assert [(s.binding.key, s.skip) for s in plan] == [
        ("TriggerMode", None),
        ("TriggerSource", "не нужен: mode=Off"),
        ("TriggerSelfTriggerPeriod", "не нужен: mode=Off"),
    ]


def test_текст_отказа_без_значения_из_рецепта():
    class Reg(SchemaBase):
        secret_managed: Annotated[bool, FieldMeta("m", ui_group="g")] = False
        token: Annotated[str, FieldMeta("t", ui_group="g", enabled_if={"secret_managed": [True]})] = ""

    bindings = {"token": Binding("genicam", "Token", "string")}
    with pytest.raises(ValueError) as exc_info:
        build_plan(Reg, {"secret_managed": True}, bindings)  # значение token не задано
    text = str(exc_info.value)
    assert "token" in text

    bad = {"tokn": Binding("genicam", "Token", "string", eps_abs=12345.0)}
    with pytest.raises(ValueError) as exc_info:
        check_bindings(Reg, bad, vendor_fields=())
    assert "tokn" in str(exc_info.value)
    assert "12345" not in str(exc_info.value)


def test_флаг_и_vendor_fields_не_требуют_привязки():
    check_bindings(Exposure, EXPOSURE_BINDINGS, vendor_fields=())
    partial = {k: v for k, v in EXPOSURE_BINDINGS.items() if k != "label"}
    with pytest.raises(ValueError) as exc_info:
        check_bindings(Exposure, partial, vendor_fields=())
    assert "label" in str(exc_info.value)
    check_bindings(Exposure, partial, vendor_fields=("label",))  # поле вендор обслуживает мимо таблицы
