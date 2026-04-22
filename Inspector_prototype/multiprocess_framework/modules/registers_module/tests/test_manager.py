# -*- coding: utf-8 -*-
"""RegistersManager: контейнер, делегирование, подписки, set_field_value."""
from __future__ import annotations

from typing import Annotated, Any, ClassVar, Dict, List

from data_schema_module import FieldMeta, FieldRouting, RegisterDispatchMeta, SchemaBase

from registers_module import RegistersManager


class _Draw(SchemaBase):
    dp: Annotated[float, FieldMeta("DP", min=0.1, max=20.0)] = 1.4


class _ReadOnly(SchemaBase):
    x: Annotated[int, FieldMeta("X", readonly=True)] = 1


class _Disp(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("p1",),
    )
    n: Annotated[int, FieldMeta("N", min=0, max=10)] = 0


def test_get_register_existing() -> None:
    d = _Draw()
    rm = RegistersManager({"draw": d})
    assert rm.get_register("draw") is d


def test_get_register_missing_returns_none() -> None:
    rm = RegistersManager({})
    assert rm.get_register("nope") is None


def test_set_register_dynamic() -> None:
    rm = RegistersManager({})
    d = _Draw()
    rm.set_register("draw", d)
    assert rm.get_register("draw") is d


def test_register_names() -> None:
    rm = RegistersManager({"a": _Draw(), "b": _Draw()})
    assert set(rm.register_names()) == {"a", "b"}


def test_model_dump_all_delegates_to_container() -> None:
    rm = RegistersManager({"draw": _Draw()})
    dumped = rm.model_dump_all()
    assert dumped == {"draw": {"dp": 1.4}}


def test_model_validate_all_delegates_to_container() -> None:
    rm = RegistersManager({"draw": _Draw()})
    rm.model_validate_all({"draw": {"dp": 2.0}}, strict=False)
    assert rm.get_register("draw") is not None
    assert rm.get_register("draw").dp == 2.0


def test_get_field_metadata_delegates() -> None:
    rm = RegistersManager({"draw": _Draw()})
    meta = rm.get_field_metadata("draw", "dp")
    assert meta.get("min") == 0.1
    assert meta.get("max") == 20.0


def test_validate_field_value_delegates() -> None:
    rm = RegistersManager({"draw": _Draw()})
    ok, err = rm.validate_field_value("draw", "dp", 0.05)
    assert ok is False
    assert err is not None
    ok2, err2 = rm.validate_field_value("draw", "dp", 5.0)
    assert ok2 is True
    assert err2 is None


def test_subscribe_and_notify() -> None:
    rm = RegistersManager({"d": _Draw()})
    seen: List[Any] = []

    def cb(v: Any) -> None:
        seen.append(v)

    rm.subscribe("d", "dp", cb)
    rm.notify_field_changed("d", "dp", 9.0)
    assert seen == [9.0]


def test_unsubscribe() -> None:
    rm = RegistersManager({"d": _Draw()})
    seen: List[Any] = []

    def cb(v: Any) -> None:
        seen.append(v)

    rm.subscribe("d", "dp", cb)
    rm.unsubscribe("d", "dp", cb)
    rm.notify_field_changed("d", "dp", 1.0)
    assert seen == []


def test_subscribe_all_global() -> None:
    rm = RegistersManager({"d": _Draw()})
    events: List[tuple] = []

    def gcb(reg: str, field: str, val: Any) -> None:
        events.append((reg, field, val))

    rm.subscribe_all(gcb)
    ok, _ = rm.set_field_value("d", "dp", 3.0)
    assert ok
    assert events == [("d", "dp", 3.0)]


def test_set_field_value_validates_and_notifies() -> None:
    rm = RegistersManager({"d": _Draw()})
    field_vals: List[Any] = []

    rm.subscribe("d", "dp", field_vals.append)
    ok, err = rm.set_field_value("d", "dp", 5.0)
    assert ok and err is None
    assert rm.get_register("d").dp == 5.0
    assert field_vals == [5.0]


def test_set_field_value_invalid_returns_error() -> None:
    rm = RegistersManager({"d": _Draw()})
    ok, err = rm.set_field_value("d", "dp", 0.01)
    assert ok is False
    assert err is not None


def test_set_field_value_calls_send_callback() -> None:
    calls: List[str] = []

    def send_cb(channel: str, *args: object) -> None:
        calls.append(channel)

    rm = RegistersManager({"x": _Disp()}, send_callback=send_cb)
    rm.set_field_value("x", "n", 5)
    assert calls == ["control_p1"]


def test_set_field_value_readonly_rejected() -> None:
    rm = RegistersManager({"r": _ReadOnly()})
    ok, err = rm.set_field_value("r", "x", 2)
    assert ok is False
    assert err is not None


def test_set_field_value_missing_register() -> None:
    rm = RegistersManager({})
    ok, err = rm.set_field_value("ghost", "x", 1)
    assert ok is False
    assert err is not None
    assert "ghost" in err


def test_set_field_value_missing_field() -> None:
    rm = RegistersManager({"d": _Draw()})
    ok, err = rm.set_field_value("d", "nonexistent", 1)
    assert ok is False
    assert err is not None
    assert "nonexistent" in err


def test_set_connection() -> None:
    rm = RegistersManager({"d": _Draw()})
    rm.set_connection("d", "new_process")
    calls: list[str] = []
    rm.set_send_callback(lambda ch, *a: calls.append(ch))
    rm.set_field_value("d", "dp", 5.0)
    assert calls == ["control_new_process"]


def test_set_send_callback() -> None:
    calls_a: list[str] = []
    calls_b: list[str] = []

    rm = RegistersManager({"x": _Disp()}, send_callback=lambda ch, *a: calls_a.append(ch))
    rm.set_field_value("x", "n", 1)
    assert len(calls_a) == 1
    rm.set_send_callback(lambda ch, *a: calls_b.append(ch))
    rm.set_field_value("x", "n", 2)
    assert len(calls_b) == 1
    assert len(calls_a) == 1


def test_set_send_callback_none_disables() -> None:
    calls: list[str] = []
    rm = RegistersManager({"x": _Disp()}, send_callback=lambda ch, *a: calls.append(ch))
    rm.set_send_callback(None)
    rm.set_field_value("x", "n", 3)
    assert calls == []


def test_notify_field_changed_only_field_observers() -> None:
    field_seen: list[Any] = []
    global_seen: list[Any] = []
    send_seen: list[int] = []
    rm = RegistersManager({"d": _Draw()}, send_callback=lambda *a: send_seen.append(1))
    rm.subscribe("d", "dp", field_seen.append)
    rm.subscribe_all(lambda r, f, v: global_seen.append(v))
    rm.notify_field_changed("d", "dp", 9.0)
    assert field_seen == [9.0]
    assert global_seen == []
    assert send_seen == []


def test_observer_exception_does_not_break_others() -> None:
    results: list[Any] = []

    def bad_cb(v: Any) -> None:
        raise RuntimeError("boom")

    def good_cb(v: Any) -> None:
        results.append(v)

    rm = RegistersManager({"d": _Draw()})
    rm.subscribe("d", "dp", bad_cb)
    rm.subscribe("d", "dp", good_cb)
    rm.set_field_value("d", "dp", 5.0)
    assert results == [5.0]


def test_global_observer_exception_does_not_break_others() -> None:
    results: list[Any] = []

    def bad_gcb(r: str, f: str, v: Any) -> None:
        raise RuntimeError("boom")

    def good_gcb(r: str, f: str, v: Any) -> None:
        results.append(v)

    rm = RegistersManager({"d": _Draw()})
    rm.subscribe_all(bad_gcb)
    rm.subscribe_all(good_gcb)
    rm.set_field_value("d", "dp", 5.0)
    assert results == [5.0]


def test_send_callback_exception_logged_not_raised() -> None:
    def bad_send(ch: str, *a: object) -> None:
        raise ConnectionError("network down")

    rm = RegistersManager({"x": _Disp()}, send_callback=bad_send)
    ok, err = rm.set_field_value("x", "n", 5)
    assert ok is True
    assert err is None
    assert rm.get_register("x") is not None
    assert rm.get_register("x").n == 5


def test_subscribe_duplicate_ignored() -> None:
    rm = RegistersManager({"d": _Draw()})
    seen: list[Any] = []
    cb = seen.append
    rm.subscribe("d", "dp", cb)
    rm.subscribe("d", "dp", cb)
    rm.set_field_value("d", "dp", 5.0)
    assert seen == [5.0]


def test_unsubscribe_nonexistent_callback_no_error() -> None:
    rm = RegistersManager({"d": _Draw()})
    rm.unsubscribe("d", "dp", lambda v: None)


def test_unsubscribe_all_nonexistent_no_error() -> None:
    rm = RegistersManager({})
    rm.unsubscribe_all(lambda r, f, v: None)


def test_validate_field_value_missing_register() -> None:
    rm = RegistersManager({})
    ok, err = rm.validate_field_value("ghost", "x", 1)
    assert ok is False
    assert err is not None
    assert "ghost" in err


def test_model_dump_validate_roundtrip() -> None:
    rm = RegistersManager({"d": _Draw()})
    rm.set_field_value("d", "dp", 7.5)
    dumped = rm.model_dump_all()
    rm2 = RegistersManager({"d": _Draw()})
    rm2.model_validate_all(dumped)
    assert rm2.get_register("d") is not None
    assert rm2.get_register("d").dp == 7.5


def test_set_field_value_snapshot_in_send_callback() -> None:
    snapshots: List[Dict[str, Any]] = []

    def send_cb(
        ch: str,
        reg: str,
        field: str,
        val: Any,
        snapshot: Dict[str, Any],
    ) -> None:
        snapshots.append(snapshot)

    rm = RegistersManager({"x": _Disp()}, send_callback=send_cb)
    rm.set_field_value("x", "n", 5)
    assert len(snapshots) == 1
    assert snapshots[0]["n"] == 5
