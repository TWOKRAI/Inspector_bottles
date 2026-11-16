"""Авторские тесты 2.2a2 S4a (А1–А5): отказ ``spawn``, проверка ``pause_action`` в ``__init_subclass__``, копия
``args``, ``conn_cb`` менеджера, отбор устройства в своём ``try`` и имена потоков ``pause_all``.

Слепые приёмочные тесты — ``test_pause_all_acceptance.py`` (не правятся). Ожидаемые значения — литералы.
Поля драйверов не трогаются (``test_no_private_driver_state.py``): двойник читается через его публичные методы.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from Services.device_hub.drivers.base import BaseDeviceDriver
from Services.device_hub.manager import DeviceManager
from Services.device_hub.spi import OpSpec

KIND = "pausedev"
OK_STOP = {"status": "ok", "op": "stop"}
SOFT = ("stop", {"level": "SOFT"})


class _Dev(BaseDeviceDriver):
    """Двойник: пишет вызовы ``call``; ``connect_ok`` / ``link_raises`` / ``mutate_args`` задаются подклассом."""

    kind = KIND
    pause_action = None
    connect_ok = True
    link_raises = False
    mutate_args = False

    def __init__(self, entry: Any) -> None:
        super().__init__(entry)
        self.log: list[tuple[str, dict]] = []
        self.guard = threading.Lock()
        self.linked = False

    @property
    def is_connected(self) -> bool:
        if self.link_raises:
            raise OSError("link read failed")
        return self.linked

    def connect(self) -> bool:
        self.linked = self.connect_ok
        return self.connect_ok

    def disconnect(self) -> None:
        self.linked = False

    def tick(self, stop_event: Any = None) -> dict | None:
        return None

    def call(self, op: str, args: dict) -> dict:
        with self.guard:
            self.log.append((op, dict(args)))
        if self.mutate_args:
            args["level"] = "MUTATED"
        return {"status": "ok"}

    def sent(self) -> list[tuple[str, dict]]:
        with self.guard:
            return list(self.log)


def _double(pause_action: tuple[str, dict] | None, **attrs: Any) -> type[_Dev]:
    return type("Double", (_Dev,), {"pause_action": pause_action, **attrs})


def _build(
    makers: dict[str, Callable[[Any], Any]],
    *,
    spawn: Callable[..., Any] | None,
    conn_cb: Callable[[str, str], None] | None = None,
    publish_cb: Callable[[str, dict], None] | None = None,
) -> DeviceManager:
    kwargs: dict[str, Any] = {"spawn": spawn}
    if conn_cb is not None:
        kwargs["conn_cb"] = conn_cb
    mgr = DeviceManager(store=None, publish_cb=publish_cb, **kwargs)
    mgr.register_driver_factory(KIND, lambda entry, proto: makers[entry.id](entry))
    assert mgr.initialize() is True
    for dev_id in makers:
        mgr.upsert({"id": dev_id, "name": dev_id, "kind": KIND, "params": {}})
    return mgr


def _run_with_deadline(fn: Callable[[], Any], join_s: float = 8.0) -> Any:
    """Вызов в daemon-потоке со сроком ожидания (зависание — красный, не вечное ожидание)."""
    box: dict[str, Any] = {}

    def body() -> None:
        try:
            box["res"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["err"] = exc

    th = threading.Thread(target=body, daemon=True)
    th.start()
    th.join(join_s)
    assert not th.is_alive(), "вызов завис"
    assert "err" not in box, repr(box.get("err"))
    return box["res"]


# --------------------------------------------------------------------------- #
# А1. spawn=None и отказ spawn — обход в этом потоке
# --------------------------------------------------------------------------- #


def _two_devices() -> dict[str, Callable[[Any], Any]]:
    return {"a": _double(SOFT), "b": _double(("stop", {}))}


def test_a1_without_spawn_runs_inline_and_all_get_command() -> None:
    mgr = _build(_two_devices(), spawn=None)
    for dev_id in ("a", "b"):
        assert mgr.connect(dev_id) is True
    res = _run_with_deadline(lambda: mgr.pause_all(time.monotonic() + 1.5))
    assert res == {"a": OK_STOP, "b": OK_STOP}
    assert mgr.get_driver("a").sent() == [("stop", {"level": "SOFT"})]
    assert mgr.get_driver("b").sent() == [("stop", {})]


def test_a1_failing_spawn_runs_inline_and_all_get_command() -> None:
    def refuse(_target: Any, *, name: str) -> Any:
        raise RuntimeError("spawn refused")

    mgr = _build(_two_devices(), spawn=refuse)
    for dev_id in ("a", "b"):
        assert mgr.connect(dev_id) is True
    res = _run_with_deadline(lambda: mgr.pause_all(time.monotonic() + 1.5))
    assert res == {"a": OK_STOP, "b": OK_STOP}
    assert mgr.get_driver("a").sent() == [("stop", {"level": "SOFT"})]
    assert mgr.get_driver("b").sent() == [("stop", {})]


# --------------------------------------------------------------------------- #
# А2. Проверка pause_action в __init_subclass__
# --------------------------------------------------------------------------- #

_SPECS = (
    OpSpec("stop", immediate=True),
    OpSpec("abort", immediate=True),
    OpSpec("park", immediate=True),
    OpSpec("enqueue_job"),
)


def _declare(pause_action: Any, specs: tuple[OpSpec, ...] = _SPECS) -> type:
    return type("Declared", (BaseDeviceDriver,), {"kind": KIND, "OP_SPECS": specs, "pause_action": pause_action})


@pytest.mark.parametrize(
    "bad",
    [("fly", {}), ("park", {}), "stop", ("stop", []), ("stop",), ("stop", {}, 1), (1, {}), ["stop", {}]],
    ids=["no_spec", "not_in_pause_ops", "str", "args_list", "len1", "len3", "op_not_str", "list_not_tuple"],
)
def test_a2_bad_pause_action_is_type_error(bad: Any) -> None:
    with pytest.raises(TypeError):
        _declare(bad)


def test_a2_op_without_immediate_flag_is_type_error() -> None:
    specs = (OpSpec("stop"), OpSpec("abort", immediate=True))
    with pytest.raises(TypeError):
        _declare(("stop", {}), specs)


def test_a2_valid_actions_are_created() -> None:
    assert _declare(("stop", {"level": "SOFT"})).pause_action == ("stop", {"level": "SOFT"})
    assert _declare(("abort", {"mode": 3})).pause_action == ("abort", {"mode": 3})
    assert _declare(None).pause_action is None


def test_a2_empty_op_specs_skips_membership_check() -> None:
    cls = _declare(("stop", {}), ())
    assert cls.pause_action == ("stop", {})
    # но PAUSE_OPS проверяется и при пустом OP_SPECS
    with pytest.raises(TypeError):
        _declare(("park", {}), ())


# --------------------------------------------------------------------------- #
# А3. Драйвер мутирует args — ClassVar цел
# --------------------------------------------------------------------------- #


def test_a3_driver_mutating_args_does_not_poison_class_pause_action() -> None:
    mgr = _build({"d1": _double(SOFT, mutate_args=True)}, spawn=None)
    assert mgr.connect("d1") is True
    first = _run_with_deadline(lambda: mgr.pause_all(time.monotonic() + 1.5))
    assert first == {"d1": OK_STOP}
    drv = mgr.get_driver("d1")
    assert type(drv).pause_action[1] == {"level": "SOFT"}
    second = _run_with_deadline(lambda: mgr.pause_all(time.monotonic() + 1.5))
    assert second == {"d1": OK_STOP}
    assert drv.sent() == [("stop", {"level": "SOFT"}), ("stop", {"level": "SOFT"})]


# --------------------------------------------------------------------------- #
# А4. conn_cb менеджера
# --------------------------------------------------------------------------- #


def test_a4_conn_cb_gets_connect_failure_and_disconnect_not_publish_cb() -> None:
    conn_calls: list[tuple[str, str]] = []
    published: list[tuple[str, dict]] = []
    mgr = _build(
        {"d1": _double(None, connect_ok=False)},
        spawn=None,
        conn_cb=lambda dev_id, conn: conn_calls.append((dev_id, conn)),
        publish_cb=lambda path, data: published.append((path, data)),
    )
    assert mgr.connect("d1") is False
    assert conn_calls == [("d1", "error")]
    mgr.disconnect("d1")
    assert conn_calls == [("d1", "error"), ("d1", "disconnected")]
    assert [p for p, _d in published if p.endswith(".conn")] == []


def test_a4_without_conn_cb_publish_cb_gets_same_paths_and_dicts_as_before() -> None:
    published: list[tuple[str, dict]] = []
    mgr = _build(
        {"d1": _double(None, connect_ok=False)},
        spawn=None,
        publish_cb=lambda path, data: published.append((path, data)),
    )
    assert mgr.connect("d1") is False
    mgr.disconnect("d1")
    assert [(p, d) for p, d in published if p.endswith(".conn")] == [
        ("devices.state.d1.conn", {"conn": "error"}),
        ("devices.state.d1.conn", {"conn": "disconnected"}),
    ]


def test_a4_conn_cb_gets_connected_on_success_and_cascade_disconnect_of_bridge_dependent() -> None:
    conn_calls: list[tuple[str, str]] = []
    mgr = DeviceManager(store=None, conn_cb=lambda dev_id, conn: conn_calls.append((dev_id, conn)))
    mgr.register_driver_factory(KIND, lambda entry, proto: _double(None)(entry))
    assert mgr.initialize() is True
    mgr.upsert({"id": "carrier", "name": "c", "kind": KIND, "params": {}})
    mgr.upsert(
        {"id": "dep", "name": "d", "kind": KIND, "params": {}, "transport": {"type": "bridge", "bridge": "carrier"}}
    )
    assert mgr.connect("carrier") is True
    assert mgr.connect("dep") is True
    mgr.disconnect("carrier")
    assert ("carrier", "connected") in conn_calls
    assert ("carrier", "disconnected") in conn_calls
    assert ("dep", "connected") in conn_calls


# --------------------------------------------------------------------------- #
# А5. Отбор в своём try; имена потоков
# --------------------------------------------------------------------------- #


def test_a5_is_connected_raising_gives_error_and_neighbours_get_command() -> None:
    mgr = _build({"bad": _double(SOFT, link_raises=True), "good": _double(SOFT)}, spawn=None)
    for dev_id in ("bad", "good"):
        assert mgr.connect(dev_id) is True
    res = _run_with_deadline(lambda: mgr.pause_all(time.monotonic() + 1.5))
    assert res["good"] == OK_STOP
    assert res["bad"]["status"] == "error"
    assert res["bad"]["op"] == ""
    assert isinstance(res["bad"]["message"], str)
    assert mgr.get_driver("good").sent() == [("stop", {"level": "SOFT"})]


def test_a5_thread_names_of_two_pause_all_calls_are_distinct() -> None:
    scope = open_scope("t", budget_s=5.0, reporter=None)
    names: list[str] = []

    def spawn(target: Callable[..., Any], *, name: str) -> Any:
        names.append(name)
        return scope.spawn(target, name=name)

    try:
        mgr = _build({"d1": _double(SOFT)}, spawn=spawn)
        assert mgr.connect("d1") is True
        for _ in range(2):
            res = _run_with_deadline(lambda: mgr.pause_all(time.monotonic() + 1.5))
            assert res == {"d1": OK_STOP}
    finally:
        scope.close()
    assert len(names) == 2
    assert len(set(names)) == 2
    assert all(n.startswith("pause-d1-") for n in names)
