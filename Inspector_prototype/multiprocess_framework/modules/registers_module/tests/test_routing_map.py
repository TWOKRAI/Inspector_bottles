# -*- coding: utf-8 -*-
"""routing_map: build_routing_map, get_routing_for_message, send_register_message."""
from __future__ import annotations

from typing import Annotated, Any, ClassVar, Dict, List, Optional, Tuple

from data_schema_module import FieldMeta, FieldRouting, RegisterDispatchMeta, SchemaBase

from registers_module import (
    MESSAGE_LOST,
    PROCESS_UNREACHABLE,
    ROUTING_NOT_FOUND,
    RegistersManager,
    build_routing_map,
    get_routing_for_message,
    send_register_message,
)


class _RegRoute(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("p1",),
    )
    a: Annotated[int, FieldMeta("a", routing=FieldRouting(channel="ch_a"))] = 1
    b: int = 2


class _RegPlain(SchemaBase):
    x: int = 0


def test_build_routing_map_with_routing_fields() -> None:
    rm = RegistersManager({"r": _RegRoute()})
    m = build_routing_map(rm)
    assert ("r", "a") in m
    assert m[("r", "a")].get("channel") == "ch_a"
    assert ("r", "b") not in m


def test_build_routing_map_no_routing_returns_empty() -> None:
    rm = RegistersManager({"p": _RegPlain()})
    assert build_routing_map(rm) == {}


def test_get_routing_for_message() -> None:
    rm = RegistersManager({"r": _RegRoute()})
    r = get_routing_for_message(rm, "r", "a")
    assert r.get("channel") == "ch_a"
    assert get_routing_for_message(rm, "r", "b") == {}


class _FakeRouter:
    def __init__(self, result: Optional[Dict[str, Any]] = None, exc: Optional[Exception] = None) -> None:
        self._result = result if result is not None else {"status": "ok"}
        self._exc = exc
        self.sent: list = []

    def send(self, message: Dict[str, Any]) -> Any:
        self.sent.append(message)
        if self._exc:
            raise self._exc
        return self._result


def test_send_register_message_success() -> None:
    rm = RegistersManager({"r": _RegRoute()})
    rmap = build_routing_map(rm)
    router = _FakeRouter()
    out = send_register_message(router, rmap, "r", "a", 42, command="write")
    assert out == {"status": "ok"}
    assert len(router.sent) == 1
    assert router.sent[0]["channel"] == "ch_a"
    assert router.sent[0]["value"] == 42


def test_send_register_message_routing_not_found() -> None:
    rm = RegistersManager({"r": _RegRoute()})
    rmap = build_routing_map(rm)
    router = _FakeRouter()
    errors: list = []

    def err_cb(kind: str, ctx: Dict[str, Any]) -> None:
        errors.append((kind, ctx))

    out = send_register_message(
        router, rmap, "r", "b", 1, error_callback=err_cb
    )
    assert out is None
    assert router.sent == []
    assert errors and errors[0][0] == ROUTING_NOT_FOUND


def test_send_register_message_process_unreachable() -> None:
    rm = RegistersManager({"r": _RegRoute()})
    rmap = build_routing_map(rm)
    router = _FakeRouter(exc=ConnectionError("boom"))
    errors: List[Tuple[str, Dict[str, Any]]] = []

    def err_cb(kind: str, ctx: Dict[str, Any]) -> None:
        errors.append((kind, ctx))

    out = send_register_message(
        router, rmap, "r", "a", 1, error_callback=err_cb
    )
    assert out is None
    assert errors and errors[0][0] == PROCESS_UNREACHABLE


def test_send_register_message_message_lost() -> None:
    rm = RegistersManager({"r": _RegRoute()})
    rmap = build_routing_map(rm)
    router = _FakeRouter(result={"status": "error", "reason": "x"})
    errors: List[Tuple[str, Dict[str, Any]]] = []

    def err_cb(kind: str, ctx: Dict[str, Any]) -> None:
        errors.append((kind, ctx))

    send_register_message(router, rmap, "r", "a", 1, error_callback=err_cb)
    assert errors and errors[0][0] == MESSAGE_LOST


def test_send_register_message_with_error_callback_empty_map() -> None:
    """error_callback вызывается при ROUTING_NOT_FOUND (пустая карта)."""
    errors: List[str] = []
    result = send_register_message(
        router=_FakeRouter(),
        routing_map={},
        register_name="camera",
        field_name="fps",
        value=30,
        error_callback=lambda code, info: errors.append(code),
    )
    assert result is None
    assert errors == [ROUTING_NOT_FOUND]


def test_build_routing_map_multiple_registers() -> None:
    """Карта из нескольких регистров с разными FieldRouting."""

    class _R1(SchemaBase):
        a: Annotated[int, FieldMeta("a", routing=FieldRouting(channel="ch1"))] = 1

    class _R2(SchemaBase):
        b: Annotated[int, FieldMeta("b", routing=FieldRouting(channel="ch2"))] = 2

    rm = RegistersManager({"r1": _R1(), "r2": _R2()})
    m = build_routing_map(rm)
    assert m[("r1", "a")]["channel"] == "ch1"
    assert m[("r2", "b")]["channel"] == "ch2"
    assert len(m) == 2
