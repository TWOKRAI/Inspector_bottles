# -*- coding: utf-8 -*-
"""Маршрутизация register_update: build_connection_map_from_registers, fan-out."""

from typing import Annotated, ClassVar

from data_schema_module import FieldMeta, FieldRouting, RegisterDispatchMeta, SchemaBase

from registers_module import RegistersManager, build_connection_map_from_registers


class _RegA(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("p1", "p2"),
    )
    x: Annotated[int, FieldMeta("x", routing=FieldRouting(channel="c1"))] = 1


class _RegB(SchemaBase):
    y: Annotated[int, FieldMeta("y", routing=FieldRouting(channel="c2"))] = 2


def test_build_connection_map_first_target_only() -> None:
    d = {"a": _RegA(), "b": _RegB()}
    m = build_connection_map_from_registers(d)
    assert m == {"a": "p1"}


def test_set_field_value_fan_out_calls_send_twice() -> None:
    calls: list[str] = []

    def send_cb(channel: str, *args: object) -> None:
        calls.append(channel)

    rm = RegistersManager({"a": _RegA()}, send_callback=send_cb)
    rm.set_field_value("a", "x", 2)
    assert calls == ["control_p1", "control_p2"]


def test_field_process_targets_override_class_dispatch() -> None:
    class _Reg(SchemaBase):
        register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
            process_targets=("class_proc",),
        )
        z: Annotated[
            int,
            FieldMeta(
                "z",
                routing=FieldRouting(
                    channel="cz",
                    process_targets=("field_proc",),
                ),
            ),
        ] = 0

    calls: list[str] = []

    def send_cb(channel: str, *args: object) -> None:
        calls.append(channel)

    rm = RegistersManager({"r": _Reg()}, send_callback=send_cb)
    rm.set_field_value("r", "z", 1)
    assert calls == ["control_field_proc"]


def test_connection_map_fallback_when_no_dispatch() -> None:
    calls: list[str] = []

    def send_cb(channel: str, *args: object) -> None:
        calls.append(channel)

    rm = RegistersManager(
        {"b": _RegB()},
        connection_map={"b": "processor"},
        send_callback=send_cb,
    )
    rm.set_field_value("b", "y", 3)
    assert calls == ["control_processor"]
