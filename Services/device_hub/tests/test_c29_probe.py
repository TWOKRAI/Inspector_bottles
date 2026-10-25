"""C-29 — проба: «Отключить» (команда плагина) посреди ручного ``connect`` робота v2 (тесты опасности, до правки).

Решение владельца (C-29): «Отключить» во время ручного ``connect`` прерывает подключение до ``sync_params`` / SERVO /
DO; правило ADR-DH-011 — простой робот, связь которого поднята (граница A3), получает ровно один SOFT, до A3 — ноль.

Обвязка драйвера — ``test_robot_v2_t53g_windows.py`` (импортом): фейковый транспорт и клиент, ``_Barrier`` (пауза
только в потоке T1). Плагин — настоящий ``DeviceHubPlugin`` (``make_ctx``), драйвер подставлен фабрикой менеджера.
T1 — поток супервизора (``_process_conn_queue``) или тика (``drv.tick``); T2 — поток теста: ``cmd_device_disconnect``.
Прогнозы на main — ``plans/robot-protocol-v2/tasks/C-29.probe.md``; тест утверждает «хотим» (литералы).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

import Services.device_hub.tests.test_robot_v2_t53g_windows as _w
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.tests.test_robot_v2_t53g_windows import (
    _ENTER_S,
    _JOIN_S,
    _Barrier,
    _bounded,
    _make_driver,
    driver_scope,  # noqa: F401 — autouse-фикстура области потоков, нужна _make_driver
)
from Services.robot_comm.core.client_v2 import SyncCancelled
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID

_DEV = "rv2"
_SYNC_S = 2.0  # «долгая» синхронизация фейка: опрос cancelled() каждые 10 мс
_WAIT_MAX_S = 0.5  # порог C2: от команды до входа в disconnect драйвера
_TLM0 = REG["TLM_PROTO_VER"]


class _Rig:
    """Плагин + драйвер робота v2 на фейках; журнал событий ввода-вывода по порядку."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        servo_tlm: int,
        do_on: bool,
        clock: Any = None,
    ) -> None:
        from Plugins.hub.device_hub.plugin import DeviceHubPlugin
        from Plugins.hub.device_hub.tests.conftest import make_ctx

        if do_on:  # действие при подключении: серво включить, DO1 включить
            monkeypatch.setattr(RobotDriverV2, "_parse_on_connect", staticmethod(lambda _raw: (True, {1: True})))
        self.drv, self.client = _make_driver(connected=False, servo_tlm=servo_tlm, clock=clock)
        self.connect_entered = threading.Event()
        self.transport = self.client.transport
        self.events: list[str] = []
        self.connect_results: list[Any] = []
        self.reset_calls: list[bool] = []  # desired_connected драйвера в момент reset_reconnect()
        self.conns: list[str] = []
        self.t_disconnect: float | None = None
        self._wrap()
        registry_file = tmp_path / "devices.yaml"
        self.ctx = make_ctx({"registry_path": str(registry_file)}, tmp_registry=registry_file)
        self.plugin = DeviceHubPlugin()
        self.plugin.configure(self.ctx)
        self.plugin.start(self.ctx)
        real_publish = self.plugin._publish_state

        def publish(path: str, value: Any) -> None:
            if path.endswith(".conn") and isinstance(value, dict):
                self.conns.append(f"{value.get('conn')}")
            real_publish(path, value)

        self.plugin._publish_state = publish
        self.plugin._manager.register_driver_factory("robot", lambda _entry, _protocol: self.drv)
        res = self.plugin.cmd_device_upsert(
            {
                "id": _DEV,
                "name": _DEV,
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": 1, "unit_id": ROBOT_UNIT_ID},
            }
        )
        assert res["status"] == "ok", res

    def _wrap(self) -> None:
        drv, client, ev = self.drv, self.client, self.events
        real_probe, real_servo = client.probe, client.servo
        real_connect, real_disconnect, real_reset = drv.connect, drv.disconnect, drv.reset_reconnect

        def probe() -> None:
            ev.append("probe")
            real_probe()

        def servo(on: bool) -> None:
            ev.append("servo")
            real_servo(on)

        def do_set(ch: int, on: bool) -> None:
            ev.append(f"do{ch}")
            bit = 1 << (ch - 1)
            words = self.transport.tlm
            i = REG["TLM_DO_MASK"] - _TLM0
            words[i] = (words[i] | bit) if on else (words[i] & ~bit)

        def sync_params(_values: Any, _epoch: int, *, cancelled: Any = None) -> None:
            ev.append("sync")

        def connect() -> bool:
            self.connect_entered.set()
            ok = real_connect()
            self.connect_results.append(ok)
            return ok

        def disconnect() -> None:
            if self.t_disconnect is None:
                self.t_disconnect = time.monotonic()
            ev.append("disconnect")
            real_disconnect()

        def reset_reconnect() -> None:
            self.reset_calls.append(drv.desired_connected)
            real_reset()

        client.probe, client.servo, client.do_set, client.sync_params = probe, servo, do_set, sync_params
        drv.connect, drv.disconnect, drv.reset_reconnect = connect, disconnect, reset_reconnect

    def cmd(self, name: str) -> dict:
        fn = getattr(self.plugin, f"cmd_device_{name}")
        return _bounded(lambda: fn({"device_id": _DEV}), 1.0, f"cmd_device_{name}")

    def proxy_mark(self) -> int:
        return len(self.ctx.state_proxy.set.call_args_list)

    def proxy_conns(self, mark: int) -> list[str]:
        """Канал оператора: ``ctx.state_proxy.set("devices.state.<id>.conn", {...})`` — сюда пишут и плагин, и
        ``publish_cb`` менеджера (``plugin.py:248``, ``:613-615``). Подряд идущие повторы схлопнуты."""
        out: list[str] = []
        for call in self.ctx.state_proxy.set.call_args_list[mark:]:
            path, value = call.args[0], call.args[1]
            if path == f"devices.state.{_DEV}.conn" and isinstance(value, dict):
                conn = f"{value.get('conn')}"
                if not out or out[-1] != conn:
                    out.append(conn)
        return out

    def after(self, mark: int, *names: str) -> int:
        return sum(1 for e in self.events[mark:] if e in names)

    def close(self) -> None:
        try:
            _bounded(lambda: self.plugin.shutdown(self.ctx), 10.0, "plugin.shutdown")
        finally:
            try:
                _bounded(self.drv.request_stop, 5.0, "request_stop")
            except Exception:  # noqa: BLE001 — уборка после теста; наблюдение уже снято
                pass


def _supervisor_window(rig: _Rig, barrier: _Barrier, *, then_connect: bool = False) -> dict[str, Any]:
    """T1 — супервизор (connect из очереди) до барьера; T2 — ``cmd_device_disconnect``; затем очередь до конца."""
    proxy_mark = rig.proxy_mark()
    assert rig.cmd("connect")["status"] == "ok"
    t1 = threading.Thread(target=rig.plugin._process_conn_queue, name="c29-supervisor", daemon=True)
    barrier.t1 = t1
    t1.start()
    if not barrier.entered.wait(_ENTER_S):
        barrier.release.set()
        t1.join(_JOIN_S)
        pytest.fail(f"окно недостижимо: барьер в потоке супервизора не сработал за {_ENTER_S} с")
    mark = len(rig.events)
    conn_mark = len(rig.conns)
    cmd = rig.cmd("disconnect")
    if then_connect:
        assert rig.cmd("connect")["status"] == "ok"
    inside = t1.is_alive() and not barrier.release.is_set()
    stopping_during = rig.drv.state.view().stopping
    barrier.release.set()
    t1.join(_JOIN_S)
    assert not t1.is_alive(), f"супервизор не вернулся за {_JOIN_S} с"
    assert inside, "команда прошла не внутри окна"
    return {
        "cmd": cmd.get("status"),
        "stopping_during": stopping_during,
        "servo_after": rig.after(mark, "servo"),
        "do_after": rig.after(mark, "do1"),
        "probe_after": rig.after(mark, "probe"),
        "probes_total": rig.events.count("probe"),
        "events_after": rig.events[mark:],
        "soft": rig.client.soft_count(),
        "connect_results": list(rig.connect_results),
        "reset_calls": list(rig.reset_calls),
        "conns_after": rig.conns[conn_mark:],
        "proxy_conns": rig.proxy_conns(proxy_mark),
        "is_connected": rig.drv.is_connected,
        "transport_open": bool(rig.transport.is_connected),
        "desired": rig.drv.desired_connected,
    }


def _scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str, **kw: Any) -> dict[str, Any]:
    servo_tlm = kw.pop("servo_tlm", 0)
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=servo_tlm, do_on=kw.pop("do_on", False))
    barrier = _Barrier()
    try:
        if arm == "probe":
            real = rig.client.on_probe
            rig.client.on_probe = lambda: (barrier.pause_if_t1(), real())
        elif arm == "first_read":
            rig.transport.on_read = barrier.pause_if_t1
        elif arm == "transport_connect":
            rig.transport.on_connect = barrier.pause_if_t1
        return _supervisor_window(rig, barrier, **kw)
    finally:
        barrier.release.set()
        rig.close()


# --------------------------------------------------------------------------------------------------
# C1 — «Отключить» внутри probe (после A3), простой неготовый робот
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def c1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _scenario(tmp_path, monkeypatch, "probe")


def test_c1_a_command_returns_ok(c1: dict[str, Any]) -> None:
    assert c1["cmd"] == "ok", c1


def test_c1_b_driver_sees_disconnect_while_connect_runs(c1: dict[str, Any]) -> None:
    assert c1["stopping_during"] is True, f"C1-b: драйвер не узнал о «Отключить» во время connect; {c1}"


def test_c1_c_no_servo_after_disconnect(c1: dict[str, Any]) -> None:
    assert c1["servo_after"] == 0, f"C1-c: SERVO после «Отключить» {c1['servo_after']}, хотим 0; {c1}"


def test_c1_d_connect_false(c1: dict[str, Any]) -> None:
    assert c1["connect_results"] == [False], f"C1-d: {c1['connect_results']}, хотим [False]; {c1}"


def test_c1_e_one_soft(c1: dict[str, Any]) -> None:
    assert c1["soft"] == 1, f"C1-e: SOFT {c1['soft']}, хотим 1; {c1}"


def test_c1_f_supervisor_keeps_desired_false(c1: dict[str, Any]) -> None:
    assert c1["reset_calls"] == [], f"C1-f: супервизор после connect поставил desired/сбросил лимит: {c1}"


def test_c1_g_no_connected_or_error_after_command(c1: dict[str, Any]) -> None:
    bad = [c for c in c1["conns_after"] if c in ("connected", "error")]
    assert bad == [], f"C1-g: после «Отключить» conn {c1['conns_after']}; {c1}"


def test_c1_h_closed_after(c1: dict[str, Any]) -> None:
    assert (c1["is_connected"], c1["transport_open"]) == (False, False), c1


# --------------------------------------------------------------------------------------------------
# C2 — «Отключить» во время долгой sync_params: сколько ждёт disconnect
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def c2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False)
    started = threading.Event()

    def slow_sync(_values: Any, _epoch: int, *, cancelled: Any = None) -> None:
        rig.events.append("sync")
        started.set()
        end = time.monotonic() + _SYNC_S
        while time.monotonic() < end:
            if cancelled is not None and cancelled():
                rig.events.append("sync_cancelled")
                raise SyncCancelled("отмена синхронизации (фейк)")
            time.sleep(0.01)

    rig.client.sync_params = slow_sync
    try:
        assert rig.cmd("connect")["status"] == "ok"
        t1 = threading.Thread(target=rig.plugin._process_conn_queue, name="c29-supervisor", daemon=True)
        t1.start()
        assert started.wait(_ENTER_S), "окно недостижимо: sync_params не начался"
        mark = len(rig.events)
        t_cmd = time.monotonic()
        cmd = rig.cmd("disconnect")
        t1.join(_SYNC_S + _JOIN_S)
        assert not t1.is_alive(), "супервизор не вернулся"
        waited = None if rig.t_disconnect is None else round(rig.t_disconnect - t_cmd, 2)
        return {
            "cmd": cmd.get("status"),
            "waited_s": waited,
            "servo_after": rig.after(mark, "servo"),
            "sync_cancelled": "sync_cancelled" in rig.events,
            "soft": rig.client.soft_count(),
            "connect_results": list(rig.connect_results),
        }
    finally:
        rig.close()


def test_c2_a_disconnect_waits_less_than_half_second(c2: dict[str, Any]) -> None:
    assert c2["waited_s"] is not None and c2["waited_s"] < _WAIT_MAX_S, f"C2-a: ждал {c2['waited_s']} с; {c2}"


def test_c2_b_sync_cancelled_no_servo(c2: dict[str, Any]) -> None:
    assert (c2["sync_cancelled"], c2["servo_after"]) == (True, 0), c2


def test_c2_c_one_soft(c2: dict[str, Any]) -> None:
    assert c2["soft"] == 1, f"C2-c: SOFT {c2['soft']}, хотим 1; {c2}"


# --------------------------------------------------------------------------------------------------
# C3 — перед SERVO (первое чтение TLM в действиях при подключении); C4 — перед DO
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def c3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _scenario(tmp_path, monkeypatch, "first_read", servo_tlm=0)


def test_c3_a_no_servo(c3: dict[str, Any]) -> None:
    assert c3["servo_after"] == 0, f"C3-a: SERVO {c3['servo_after']}, хотим 0; {c3}"


def test_c3_b_connect_false_one_soft(c3: dict[str, Any]) -> None:
    assert (c3["connect_results"], c3["soft"]) == ([False], 1), c3


@pytest.fixture
def c4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _scenario(tmp_path, monkeypatch, "first_read", servo_tlm=1, do_on=True)


def test_c4_a_no_do(c4: dict[str, Any]) -> None:
    assert c4["do_after"] == 0, f"C4-a: DO {c4['do_after']}, хотим 0; {c4}"


def test_c4_b_connect_false_one_soft(c4: dict[str, Any]) -> None:
    assert (c4["connect_results"], c4["soft"]) == ([False], 1), c4


# --------------------------------------------------------------------------------------------------
# C5 — до A3: внутри transport.connect()
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def c5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _scenario(tmp_path, monkeypatch, "transport_connect")


def test_c5_a_no_probe_no_servo(c5: dict[str, Any]) -> None:
    assert (c5["probe_after"], c5["servo_after"]) == (0, 0), c5


def test_c5_b_zero_soft_connect_false(c5: dict[str, Any]) -> None:
    assert (c5["soft"], c5["connect_results"]) == (0, [False]), c5


def test_c5_c_closed_after(c5: dict[str, Any]) -> None:
    assert (c5["is_connected"], c5["transport_open"]) == (False, False), c5


# --------------------------------------------------------------------------------------------------
# C6 — connect -> «Отключить» -> «Подключить» подряд (ABA), окно — probe первого connect
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def c6(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _scenario(tmp_path, monkeypatch, "probe", then_connect=True)


def test_c6_a_servo_only_after_disconnect(c6: dict[str, Any]) -> None:
    order = [e for e in c6["events_after"] if e in ("servo", "disconnect")]
    assert order == ["disconnect", "servo"], f"C6-a: порядок {order}; {c6}"


def test_c6_b_final_connected_one_soft(c6: dict[str, Any]) -> None:
    assert (c6["is_connected"], c6["soft"], c6["desired"]) == (True, 1, True), c6


def test_c6_c_connect_results(c6: dict[str, Any]) -> None:
    assert c6["connect_results"] == [False, True], f"C6-c: {c6['connect_results']}; {c6}"


# --------------------------------------------------------------------------------------------------
# C7 — переподключение тика против команды «Отключить» (окно — probe тика); супервизор занят не этим
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def c7(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False)
    barrier = _Barrier()
    try:
        assert rig.cmd("connect")["status"] == "ok"
        _bounded(rig.plugin._process_conn_queue, 5.0, "connect")
        assert rig.drv.is_connected and rig.drv.desired_connected, "настройка: робот не подключён"
        rig.transport.is_connected = False  # связь упала вне тика
        rig.transport.tlm[REG["TLM_SERVO"] - _TLM0] = 0  # робот снял серво: переподключение шлёт SERVO
        real = rig.client.on_probe
        rig.client.on_probe = lambda: (barrier.pause_if_t1(), real())
        box: dict[str, Any] = {}
        t1 = threading.Thread(target=lambda: box.update(snap=rig.drv.tick()), name="c29-tick", daemon=True)
        barrier.t1 = t1
        t1.start()
        if not barrier.entered.wait(_ENTER_S):
            barrier.release.set()
            t1.join(_JOIN_S)
            pytest.fail("окно недостижимо: тик не дошёл до probe")
        mark = len(rig.events)
        cmd = rig.cmd("disconnect")
        stopping_during = rig.drv.state.view().stopping
        barrier.release.set()
        t1.join(_JOIN_S)
        assert not t1.is_alive(), "тик не вернулся"
        tick_connected = rig.drv.is_connected
        _bounded(rig.plugin._process_conn_queue, 5.0, "disconnect")
        return {
            "cmd": cmd.get("status"),
            "stopping_during": stopping_during,
            "servo_after": rig.after(mark, "servo"),
            "tick_connected": tick_connected,
            "soft": rig.client.soft_count(),
            "transport_open": bool(rig.transport.is_connected),
        }
    finally:
        barrier.release.set()
        rig.close()


def test_c7_a_tick_no_servo_after_command(c7: dict[str, Any]) -> None:
    assert c7["servo_after"] == 0, f"C7-a: SERVO тика после «Отключить» {c7['servo_after']}; {c7}"


def test_c7_b_tick_not_connected(c7: dict[str, Any]) -> None:
    assert c7["tick_connected"] is False, c7


def test_c7_c_one_soft_closed(c7: dict[str, Any]) -> None:
    assert (c7["soft"], c7["transport_open"]) == (1, False), c7


def test_c29_harness_uses_shared_scope() -> None:
    """Сторож обвязки: фабрика драйвера окон T5.3g доступна (область потоков открыта фикстурой)."""
    assert _w._SCOPE is not None


# --------------------------------------------------------------------------------------------------
# Итерация 2 (стадия 0 р.1, п.4): C8 = окно О3, C9 = окно О11, C10 = ожидание TLM после SERVO
# --------------------------------------------------------------------------------------------------


def _drop_link(rig: _Rig) -> None:
    """Робот подключён через очередь, затем связь падает вне тика, робот снимает серво."""
    assert rig.cmd("connect")["status"] == "ok"
    _bounded(rig.plugin._process_conn_queue, 5.0, "connect")
    assert rig.drv.is_connected and rig.drv.desired_connected, "настройка: робот не подключён"
    rig.transport.is_connected = False
    rig.transport.tlm[REG["TLM_SERVO"] - _TLM0] = 0


@pytest.fixture
def c8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """О3: тик держит ``_param_lock`` (пауза в probe переподключения); ручной connect из очереди ждёт замок; K."""
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False)
    barrier = _Barrier()
    try:
        _drop_link(rig)
        real = rig.client.on_probe
        rig.client.on_probe = lambda: (barrier.pause_if_t1(), real())
        tick = threading.Thread(target=rig.drv.tick, name="c29-tick", daemon=True)
        barrier.t1 = tick
        tick.start()
        if not barrier.entered.wait(_ENTER_S):
            barrier.release.set()
            tick.join(_JOIN_S)
            pytest.fail("окно недостижимо: тик не дошёл до probe")
        rig.connect_entered.clear()
        assert rig.cmd("connect")["status"] == "ok"
        sup = threading.Thread(target=rig.plugin._process_conn_queue, name="c29-supervisor", daemon=True)
        sup.start()
        assert rig.connect_entered.wait(_ENTER_S), "окно недостижимо: супервизор не вошёл в connect"
        time.sleep(0.2)  # ручной connect стоит на _param_lock (тик держит)
        waiting = sup.is_alive() and len(rig.connect_results) == 1
        mark = len(rig.events)
        cmd = rig.cmd("disconnect")
        barrier.release.set()
        tick.join(_JOIN_S)
        sup.join(_JOIN_S)
        assert not tick.is_alive() and not sup.is_alive(), "тик или супервизор не вернулся"
        assert waiting, f"ручной connect не ждал замок: {rig.connect_results}"
        return {
            "cmd": cmd.get("status"),
            "probe_after": rig.after(mark, "probe"),
            "servo_after": rig.after(mark, "servo"),
            "events_after": rig.events[mark:],
            "connect_results": list(rig.connect_results),
            "soft": rig.client.soft_count(),
            "transport_open": bool(rig.transport.is_connected),
        }
    finally:
        barrier.release.set()
        rig.close()


def test_c8_a_waiting_manual_connect_no_probe_no_servo(c8: dict[str, Any]) -> None:
    assert (c8["probe_after"], c8["servo_after"]) == (0, 0), f"C8-a: {c8}"


def test_c8_b_one_soft_closed(c8: dict[str, Any]) -> None:
    assert (c8["soft"], c8["transport_open"]) == (1, False), f"C8-b: {c8}"


@pytest.fixture
def c9(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """О11: тик прошёл обе проверки desired (пауза на первом чтении часов в потоке тика), затем K, затем C0 тика."""
    barrier = _Barrier()

    def clock() -> float:
        barrier.pause_if_t1()
        return time.monotonic()

    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False, clock=clock)
    try:
        _drop_link(rig)
        tick = threading.Thread(target=rig.drv.tick, name="c29-tick", daemon=True)
        barrier.t1 = tick
        tick.start()
        if not barrier.entered.wait(_ENTER_S):
            barrier.release.set()
            tick.join(_JOIN_S)
            pytest.fail("окно недостижимо: тик не дошёл до часов после проверок desired")
        mark = len(rig.events)
        cmd = rig.cmd("disconnect")
        inside = tick.is_alive() and not barrier.release.is_set()
        barrier.release.set()
        tick.join(_JOIN_S)
        assert not tick.is_alive(), "тик не вернулся"
        assert inside, "команда прошла не внутри окна"
        tick_connected = rig.drv.is_connected
        _bounded(rig.plugin._process_conn_queue, 5.0, "disconnect")
        return {
            "cmd": cmd.get("status"),
            "probe_after": rig.after(mark, "probe"),
            "servo_after": rig.after(mark, "servo"),
            "tick_connected": tick_connected,
            "soft": rig.client.soft_count(),
            "transport_open": bool(rig.transport.is_connected),
        }
    finally:
        barrier.release.set()
        rig.close()


def test_c9_a_tick_past_checks_no_probe_no_servo(c9: dict[str, Any]) -> None:
    assert (c9["probe_after"], c9["servo_after"]) == (0, 0), f"C9-a: {c9}"


def test_c9_b_link_down_zero_soft(c9: dict[str, Any]) -> None:
    assert (c9["soft"], c9["tick_connected"], c9["transport_open"]) == (0, False, False), f"C9-b: {c9}"


@pytest.fixture
def c10(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """K после SERVO, робот не подтверждает SERVO в TLM: ``_await_tlm`` ждёт до своего срока (2,0 с)."""
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False)
    servo_sent = threading.Event()

    def servo_unconfirmed(_on: bool) -> None:
        rig.events.append("servo")
        servo_sent.set()

    rig.client.servo = servo_unconfirmed
    try:
        assert rig.cmd("connect")["status"] == "ok"
        sup = threading.Thread(target=rig.plugin._process_conn_queue, name="c29-supervisor", daemon=True)
        sup.start()
        assert servo_sent.wait(_ENTER_S), "окно недостижимо: SERVO не отправлен"
        t_cmd = time.monotonic()
        cmd = rig.cmd("disconnect")
        sup.join(_JOIN_S)
        assert not sup.is_alive(), "супервизор не вернулся"
        waited = None if rig.t_disconnect is None else round(rig.t_disconnect - t_cmd, 2)
        return {
            "cmd": cmd.get("status"),
            "waited_s": waited,
            "soft": rig.client.soft_count(),
            "connect_results": list(rig.connect_results),
        }
    finally:
        rig.close()


def test_c10_a_disconnect_waits_less_than_half_second(c10: dict[str, Any]) -> None:
    assert c10["waited_s"] is not None and c10["waited_s"] < _WAIT_MAX_S, f"C10-a: ждал {c10['waited_s']} с; {c10}"


def test_c10_b_one_soft(c10: dict[str, Any]) -> None:
    assert c10["soft"] == 1, f"C10-b: SOFT {c10['soft']}, хотим 1; {c10}"


def test_c10_c_connect_false(c10: dict[str, Any]) -> None:
    assert c10["connect_results"] == [False], f"C10-c: {c10['connect_results']}; {c10}"


# --------------------------------------------------------------------------------------------------
# Итерация 3 (ответы владельца В3, В4): C11 — статусы conn; C12 — jog, C13 — задание в окне «Отключить»
# НЕ ПРОГНАНО (пауза владельца 2026-10-25): прогноз — C-29.probe.md, «Итерация 3»; факта нет
# --------------------------------------------------------------------------------------------------

_TEXT_DISCONNECTING = "идёт отключение робота"  # литерал брифа C-29 (DESIGN п.7), не из кода
_JOB = {"x_mm": 10.0, "y_mm": 20.0}


def test_c11_a_aborted_connect_statuses(c1: dict[str, Any]) -> None:
    """В3: прерванный по «Отключить» connect — connecting -> disconnecting -> disconnected, без error/connected."""
    want = ["connecting", "disconnecting", "disconnected"]
    assert c1["proxy_conns"] == want, f"C11-a: {c1['proxy_conns']}; {c1}"


def test_c11_b_pair_plain_connect_sees_connected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Парная к C11-a (достижимость канала): connect без «Отключить» виден как connecting -> connected."""
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False)
    try:
        mark = rig.proxy_mark()
        assert rig.cmd("connect")["status"] == "ok"
        _bounded(rig.plugin._process_conn_queue, 5.0, "connect")
        assert rig.proxy_conns(mark) == ["connecting", "connected"], rig.proxy_conns(mark)
    finally:
        rig.close()


def _connected_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Rig:
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False)
    assert rig.cmd("connect")["status"] == "ok"
    _bounded(rig.plugin._process_conn_queue, 5.0, "connect")
    assert rig.drv.is_connected, "настройка: робот не подключён"
    return rig


@pytest.fixture
def c12(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """В4: «Отключить» нажато, disconnect из очереди ещё не шёл; jog_hold в этом окне."""
    rig = _connected_rig(tmp_path, monkeypatch)
    try:
        jogs_before = len(rig.client.jog_conts)
        assert rig.cmd("disconnect")["status"] == "ok"
        reply = _bounded(lambda: rig.drv.call("jog_hold", {"dir": 1, "spd": 20}), 5.0, "jog_hold")
        jogs = len(rig.client.jog_conts) - jogs_before
        _bounded(rig.plugin._process_conn_queue, 5.0, "disconnect")
        return {"reply": reply, "jog_conts": jogs}
    finally:
        rig.close()


def test_c12_a_jog_refused_in_window(c12: dict[str, Any]) -> None:
    assert c12["reply"] == {"status": "error", "message": _TEXT_DISCONNECTING}, f"C12-a: {c12}"


def test_c12_b_no_jog_frame_in_window(c12: dict[str, Any]) -> None:
    assert c12["jog_conts"] == 0, f"C12-b: JOG_CONT {c12['jog_conts']}, хотим 0; {c12}"


def test_c12_c_pair_jog_outside_window_reaches_robot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Парная к C12: без «Отключить» jog_hold доходит до робота (1 JOG_CONT)."""
    rig = _connected_rig(tmp_path, monkeypatch)
    try:
        reply = _bounded(lambda: rig.drv.call("jog_hold", {"dir": 1, "spd": 20}), 5.0, "jog_hold")
        assert reply.get("status") == "ok", reply
        assert len(rig.client.jog_conts) == 1, rig.client.jog_conts
        _bounded(lambda: rig.drv.call("jog_release", {}), 5.0, "jog_release")
    finally:
        rig.close()


@pytest.fixture
def c13(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """В4: задание в окне «Отключить» → явный отказ."""
    rig = _connected_rig(tmp_path, monkeypatch)
    try:
        assert rig.cmd("disconnect")["status"] == "ok"
        reply = _bounded(lambda: rig.drv.call("enqueue_job", dict(_JOB)), 5.0, "enqueue_job")
        _bounded(rig.plugin._process_conn_queue, 5.0, "disconnect")
        return {"reply": reply}
    finally:
        rig.close()


def test_c13_a_job_refused_in_window(c13: dict[str, Any]) -> None:
    reply = c13["reply"]
    assert (reply.get("status"), reply.get("message")) == ("error", _TEXT_DISCONNECTING), f"C13-a: {c13}"


def test_c13_b_pair_job_outside_window_queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Парная к C13: без «Отключить» задание встаёт в очередь."""
    rig = _connected_rig(tmp_path, monkeypatch)
    try:
        reply = _bounded(lambda: rig.drv.call("enqueue_job", dict(_JOB)), 5.0, "enqueue_job")
        assert reply == {"status": "ok", "queue_len": 1}, reply
    finally:
        rig.close()
