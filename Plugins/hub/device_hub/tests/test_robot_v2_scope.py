"""Тесты-сторожа автора T5.3a (plans/robot-protocol-v2/tasks/T5.3a.md, «Бриф: файлы и красные», S1-S16).

Purpose:
    Окна гонки и ветки отказов, которые слепая приёмка (``test_robot_v2_scope_acceptance.py``) не покрывает:
    V1 (``disconnect`` между ACK ``JOG_CONT`` и записью ``self._jog``), окно ``_launch`` при ``_jog_stopping``,
    порядок итога ``.program``, отказы ``spawn`` (область закрыта / имя занято / после ACK), порядок старта
    поводка, ``jog_release`` при ``run.handle is None``, видимость выжившего потока, ``logger.exception`` в
    ``DeviceManager._on_shutdown``, HARD в фазе 1, защёлки ``_stopping`` / ``_shutdown`` / ``_shutting_down``,
    прерывание ``tick_loop``, повтор стопа в ``on_progress``. Швы — по К8 брифа: обёртки ``spawn`` и методов клиента,
    не барьер на входе метода. Стенд — ``E2eRig`` (sim v2 на свободном порту); блокирующие вызовы — daemon-поток
    с дедлайном (``bounded``).

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.base_manager.interfaces import ScopeClosedError
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Plugins.hub.device_hub.tests.test_t53r2_stop_hazards import _Rig as _HoldRig
from Services.device_hub.drivers import robot_driver_v2
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, RecordingCore, bounded

_JOG = {"dir": 1, "spd": 20}
_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0  # connect включает sync_params (58 записей PARAM_SET)
_CMD_JOG = re.compile(r"\[v2\] CMD seq=(\d+) op=JOG_CONT")
_TEXT_STOPPING = "драйвер робота останавливается"
_TEXT_SCOPE_CLOSED = "область потоков хаба закрыта"
_TEXT_NAME_BUSY = "имя потока драйвера занято"
_TEXT_SURVIVED = "поток драйвера не вышел за срок"
_BUSY_JOG = {"status": "error", "message": "робот в режиме jog"}
_SCOPE_CONTEXT = "device_hub.scope"
# Предел shutdown в S9-плагине при фазе 1 +0.5 с. Замер (light, 3 прогона на сторону): эталон 2.500-2.516 с (весь срок
# 2.5 с), инъекция «scope.close с фиксированным бюджетом 2.5 с» 3.000-3.016 с. Литерал 2.75 с = эталон + ~0.23 с запаса
# на нагрузку и на 0.25 с ниже инъекции; прежние 3.5 с пропускали инъекцию
_S9_LIMIT_S = 2.75


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


class Rec:
    """``publish``: копит ``(path, payload)`` под замком; ``delay_final`` задерживает запись итога программы."""

    def __init__(self, delay_final: tuple[str, float] | None = None) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []
        self._delay_final = delay_final

    def __call__(self, path: str, payload: Any) -> None:
        if (
            self._delay_final is not None
            and isinstance(payload, dict)
            and payload.get("name") == self._delay_final[0]
            and payload.get("state") == "done"
        ):
            time.sleep(self._delay_final[1])
        with self._lock:
            self._items.append((path, payload))

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self._items)

    def at(self, dev_id: str, leaf: str) -> list[Any]:
        path = f"devices.state.{dev_id}.{leaf}"
        return [payload for p, payload in self.items() if p == path]

    def programs(self, dev_id: str) -> list[tuple[str, str]]:
        return [(p["name"], p["state"]) for p in self.at(dev_id, "program") if isinstance(p, dict) and "state" in p]


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while True:
        if pred():
            return
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.01)


def _moving(core: RecordingCore) -> int:
    return core.ticks()[-1].moving


def _jog_seqs(core: RecordingCore) -> list[int]:
    return [int(m.group(1)) for _, text in core.events() if (m := _CMD_JOG.search(text))]


def _has_err13(core: RecordingCore, seq: int) -> bool:
    return any(f"[v2] ERR seq={seq} errno=13" in text for _, text in core.events())


def _transport(port: int) -> dict:
    return {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID}


def _entry(port: int, dev_id: str = "r1", params: dict | None = None) -> DeviceEntry:
    return DeviceEntry(
        id=dev_id, name=dev_id, kind="robot", protocol="delta_v2", transport=_transport(port), params=dict(params or {})
    )


def _legs(name: str, legs: int) -> tuple[Program, dict[str, Point]]:
    """``legs`` ходов JOINT между двумя точками; одна нога ~0.27 с sim (20 ног ~5.4 с)."""
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    steps = tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(legs))
    return Program(name=name, steps=steps), points


def _start(drv: Any, legs: int, name: str) -> dict:
    program, points = _legs(name, legs)
    return bounded(lambda: drv.start_program(program, points, None, name=name), _CALL_DEADLINE_S)


@contextmanager
def _bench(
    *,
    wrap: Callable[[Callable[..., Any]], Callable[..., Any]] | None = None,
    params: dict | None = None,
    rec: Rec | None = None,
) -> Iterator[tuple[RobotDriverV2, E2eRig, Rec, Any]]:
    """Стенд: sim + область ``g53`` + подключённый драйвер ``r1``. ``wrap(spawn)`` подменяет ``spawn`` драйвера."""
    rec = rec or Rec()
    with E2eRig() as rig:
        scope = open_scope("g53", budget_s=2.5)
        spawn = wrap(scope.spawn) if wrap is not None else scope.spawn
        drv = RobotDriverV2(_entry(rig.port, params=params), None, publish=rec, spawn=spawn)
        try:
            assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True
            drv.desired_connected = True
            yield drv, rig, rec, scope
        finally:
            for fn in (drv.disconnect, scope.close):
                try:
                    bounded(fn, _CALL_DEADLINE_S)
                except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                    pass


def _plugin_with_robots(
    tmp_path: Path, ports: dict[str, int], params: dict | None = None
) -> tuple[DeviceHubPlugin, Any]:
    """Плагин на ``make_ctx``: реестр во ``tmp_path``, роботы в ``recipe_devices``, подключение — разбор очереди."""
    registry_file = tmp_path / "devices.yaml"
    recipe = [
        {
            "id": dev_id,
            "name": dev_id,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": _transport(port),
            "params": dict(params or {}),
        }
        for dev_id, port in ports.items()
    ]
    ctx = make_ctx({"registry_path": str(registry_file), "recipe_devices": recipe}, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    for dev_id in ports:
        assert plugin.cmd_device_connect({"device_id": dev_id})["status"] == "ok"
    bounded(plugin._process_conn_queue, _CONNECT_DEADLINE_S)
    assert sorted(plugin._manager.connected_ids()) == sorted(ports), "роботы не подключились через очередь плагина"
    return plugin, ctx


def _shutdown_quietly(plugin: DeviceHubPlugin, ctx: Any) -> None:
    try:
        bounded(lambda: plugin.shutdown(ctx), 10.0)
    except Exception:  # noqa: BLE001 — уборка; повторный shutdown безвреден
        pass


def _scope_reports(ctx: Any) -> list[Any]:
    return [c for c in ctx.health.report_error.call_args_list if c.kwargs.get("context") == _SCOPE_CONTEXT]


def _fake_run_chunks(done_evt: threading.Event) -> Callable[..., None]:
    """Исполнитель, не смотрящий стопы: живёт до ``done_evt`` или 6.0 с."""

    def run_chunks(*_a: Any, **_k: Any) -> None:
        end = time.monotonic() + 6.0
        while not done_evt.wait(0.05) and time.monotonic() < end:
            pass

    return run_chunks


def _wait_running(rec: Rec, dev_id: str = "r1") -> None:
    _until(lambda: any(s == "running" for _, s in rec.programs(dev_id)), 10.0, "program перешла в running")


# --------------------------------------------------------------------------------------------------
# S1 — V1: disconnect между ACK JOG_CONT и записью self._jog
# --------------------------------------------------------------------------------------------------


def test_s1_disconnect_between_jog_ack_and_jog_record_still_stops_robot() -> None:
    with _bench() as (drv, rig, _rec, _scope):
        core = rig.core
        client = drv._client
        real = client.jog_cont
        acked, go = threading.Event(), threading.Event()

        def jog_cont(*a: Any, **k: Any) -> Any:
            result = real(*a, **k)
            acked.set()
            go.wait(2.0)
            return result

        client.jog_cont = jog_cont  # type: ignore[method-assign]
        hold_res: list[dict] = []
        a = threading.Thread(target=lambda: hold_res.append(drv.call("jog_hold", _JOG)), daemon=True)
        b = threading.Thread(target=drv.disconnect, daemon=True)
        a.start()
        assert acked.wait(2.0), "JOG_CONT не подтверждён"
        b.start()
        time.sleep(0.2)  # disconnect ждёт _jog_tx_lock, который держит jog_hold
        go.set()
        a.join(5.0)
        b.join(5.0)
        assert not a.is_alive() and not b.is_alive()
        seq = _jog_seqs(core)[-1]
        _until(lambda: _has_err13(core, seq), 1.0, "стоп jog дошёл (errno=13 для seq JOG_CONT)")
        _until(lambda: _moving(core) == 0, 1.0, "sim: moving == 0")


# --------------------------------------------------------------------------------------------------
# S2 — окно _launch при _jog_stopping
# --------------------------------------------------------------------------------------------------


def test_s2_launch_during_jog_release_stop_in_flight_is_busy_jog() -> None:
    with _bench() as (drv, rig, _rec, _scope):
        assert drv.call("jog_hold", _JOG)["status"] == "ok"
        time.sleep(0.1)
        client = drv._client
        real_stop = client.issue_stop
        entered, gate = threading.Event(), threading.Event()

        def stop(level: int) -> Any:
            entered.set()
            gate.wait(2.0)
            return real_stop(level)

        client.issue_stop = stop  # type: ignore[method-assign]
        rel = threading.Thread(target=lambda: drv.call("jog_release", {}), daemon=True)
        rel.start()
        try:
            assert entered.wait(3.0), "стоп jog_release не начался"
            assert _start(drv, 4, "p2") == _BUSY_JOG
        finally:
            gate.set()
            rel.join(5.0)
            client.issue_stop = real_stop  # type: ignore[method-assign]
        assert not rel.is_alive()


# --------------------------------------------------------------------------------------------------
# S3 — итог .program до снятия _busy
# --------------------------------------------------------------------------------------------------


def test_s3_final_program_state_published_before_busy_cleared() -> None:
    # итог первой программы публикуется медленно (0.15 с): запуск второй, как только _busy снят, не должен
    # обогнать запись итога
    rec = Rec(delay_final=("pa", 0.15))
    with _bench(rec=rec) as (drv, _rig, _r, _scope):
        assert _start(drv, 1, "pa")["status"] == "ok"
        second: dict = {}
        end = time.monotonic() + 10.0
        while time.monotonic() < end:
            second = _start(drv, 1, "pb")
            if second.get("status") == "ok":
                break
            time.sleep(0.002)
        assert second.get("status") == "ok", second
        _until(lambda: ("pb", "done") in rec.programs("r1"), 10.0, "вторая программа дошла до done")
        states = rec.programs("r1")
        assert states.index(("pa", "done")) < states.index(("pb", "running")), states


# --------------------------------------------------------------------------------------------------
# S4 / S5 — отказы spawn
# --------------------------------------------------------------------------------------------------


def _failing_once(exc: Exception) -> tuple[Callable[[Callable[..., Any]], Callable[..., Any]], list[int]]:
    """``wrap`` для ``_bench``: первый ``spawn`` бросает ``exc`` вместо настоящего, дальше — настоящий."""
    calls: list[int] = []

    def wrap(real: Callable[..., Any]) -> Callable[..., Any]:
        def spawn(target: Callable[..., Any], *, name: str) -> Any:
            calls.append(1)
            if len(calls) == 1:
                raise exc
            return real(target, name=name)

        return spawn

    return wrap, calls


def test_s4_spawn_scope_closed_clears_flags_and_answers_text() -> None:
    wrap_jog, _ = _failing_once(ScopeClosedError("t"))
    with _bench(wrap=wrap_jog) as (drv, _rig, _rec, _scope):
        resp = drv.call("jog_hold", _JOG)
        assert resp == {"status": "error", "message": _TEXT_SCOPE_CLOSED}
        assert drv.call("jog_hold", _JOG)["status"] == "ok", "флаги не сняты: следующий jog_hold не прошёл"
        assert drv.call("jog_release", {})["status"] == "ok"
    wrap_prog, _ = _failing_once(ScopeClosedError("t"))
    with _bench(wrap=wrap_prog) as (drv, _rig, _rec, _scope):
        assert _start(drv, 4, "p4") == {"status": "error", "message": _TEXT_SCOPE_CLOSED}
        assert _start(drv, 4, "p4")["status"] == "ok", "флаги не сняты: следующая программа не запущена"


def test_s5_spawn_value_error_answers_name_busy_and_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    wrap, _ = _failing_once(ValueError("t"))
    with _bench(wrap=wrap) as (drv, _rig, _rec, _scope):
        resp = drv.call("jog_hold", _JOG)
        assert resp == {"status": "error", "message": _TEXT_NAME_BUSY}
        assert any(r.levelno >= logging.ERROR and "занято" in r.getMessage() for r in caplog.records), [
            r.getMessage() for r in caplog.records
        ]
        assert drv.call("jog_hold", _JOG)["status"] == "ok", "флаги не сняты"
        assert drv.call("jog_release", {})["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# S6 — spawn поводка бросил после ACK JOG_CONT: стоп уходит сам
# --------------------------------------------------------------------------------------------------


def test_s6_spawn_failure_after_jog_ack_sends_stop() -> None:
    wrap, _ = _failing_once(ScopeClosedError("t"))
    with _bench(wrap=wrap) as (drv, rig, rec, _scope):
        core = rig.core
        errors_before = len(rec.at("r1", "last_error"))
        resp = drv.call("jog_hold", _JOG)
        returned = time.monotonic()
        assert resp["status"] == "error"
        seq = _jog_seqs(core)[-1]
        # меньше срока поводка прошивки (300 мс): без стопа робот встал бы сам, но без errno=13
        _until(lambda: _has_err13(core, seq), max(0.0, 0.15 - (time.monotonic() - returned)), "errno=13 для seq")
        _until(lambda: _moving(core) == 0, max(0.0, 0.15 - (time.monotonic() - returned)), "sim: moving == 0")
        assert len(rec.at("r1", "last_error")) == errors_before, "собственный стоп попал в last_error"


# --------------------------------------------------------------------------------------------------
# S7 — порядок старта поводка: _last_hold до spawn
# --------------------------------------------------------------------------------------------------


def test_s7_last_hold_written_before_lease_thread_starts() -> None:
    def wrap(real: Callable[..., Any]) -> Callable[..., Any]:
        def spawn(target: Callable[..., Any], *, name: str) -> Any:
            handle = real(target, name=name)  # поток уже идёт
            time.sleep(0.05)  # окно «поток идёт, run.handle ещё не записан»
            return handle

        return spawn

    with _bench(wrap=wrap) as (drv, rig, _rec, _scope):
        core = rig.core
        assert drv.call("jog_hold", _JOG)["status"] == "ok"
        assert drv.call("jog_release", {})["status"] == "ok"
        time.sleep(0.3)  # больше окна Д3 (0.2 с): прежний _last_hold устарел
        assert drv.call("jog_hold", _JOG)["status"] == "ok"
        seq = _jog_seqs(core)[-1]
        time.sleep(0.1)
        assert _moving(core) == 1, "поток поводка увидел устаревший _last_hold и остановил jog"
        assert not _has_err13(core, seq), "стоп jog ушёл сразу после старта"
        assert drv.call("jog_release", {})["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# S8 — jog_release во время spawn (run.handle is None)
# --------------------------------------------------------------------------------------------------


def test_s8_jog_release_while_spawn_in_flight_handle_none() -> None:
    in_spawn, go = threading.Event(), threading.Event()

    def wrap(real: Callable[..., Any]) -> Callable[..., Any]:
        def spawn(target: Callable[..., Any], *, name: str) -> Any:
            in_spawn.set()
            go.wait(2.0)
            return real(target, name=name)

        return spawn

    with _bench(wrap=wrap) as (drv, rig, _rec, _scope):
        core = rig.core
        hold_res: list[dict] = []
        rel_res: list[dict] = []
        a = threading.Thread(target=lambda: hold_res.append(drv.call("jog_hold", _JOG)), daemon=True)
        a.start()
        assert in_spawn.wait(3.0), "spawn не начался"
        b = threading.Thread(target=lambda: rel_res.append(drv.call("jog_release", {})), daemon=True)
        b.start()
        time.sleep(0.1)
        go.set()
        released = time.monotonic()
        a.join(5.0)
        b.join(5.0)
        assert not a.is_alive() and not b.is_alive()
        assert rel_res == [{"status": "ok"}], rel_res
        seq = _jog_seqs(core)[-1]
        left = max(0.0, 0.15 - (time.monotonic() - released))
        _until(lambda: _has_err13(core, seq), left, "errno=13 для seq JOG_CONT")
        _until(lambda: _moving(core) == 0, left, "sim: moving == 0")


# --------------------------------------------------------------------------------------------------
# S9 — выживший виден
# --------------------------------------------------------------------------------------------------


def test_s9_survivor_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _s9_part_disconnect(monkeypatch)
    _s9_part_plugin(tmp_path)


def _s9_part_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(robot_driver_v2, "_PROGRAM_JOIN_S", 0.3)
    done_evt = threading.Event()
    with _bench() as (drv, _rig, rec, _scope):
        try:
            drv._client.run_chunks = _fake_run_chunks(done_evt)  # type: ignore[method-assign]
            assert _start(drv, 4, "p9")["status"] == "ok"
            _wait_running(rec)
            errs_before = drv.stats["tx_err"]
            started = time.monotonic()
            bounded(drv.disconnect, _CALL_DEADLINE_S)
            assert time.monotonic() - started <= 1.0
            assert rec.at("r1", "last_error")[-1] == _TEXT_SURVIVED
            assert drv.stats["tx_err"] == errs_before + 1
        finally:
            done_evt.set()


def _s9_part_plugin(tmp_path: Path) -> None:
    done_evt = threading.Event()
    plugin = ctx = None
    try:
        with _HoldRig() as rig:
            plugin, ctx = _plugin_with_robots(tmp_path, {"r1": rig.port})
            drv = plugin._manager.get_driver("r1")
            drv._client.run_chunks = _fake_run_chunks(done_evt)
            assert _start(drv, 4, "p9")["status"] == "ok"
            _until(lambda: drv._prog_alive, 5.0, "исполнитель запущен")
            # Фаза 1 дольше на 0.5 с: робот держит ответ на запись стопа (не патч драйвера). Тогда scope.close с
            # остатком срока (2.5 - 0.5 = 2.0 с) и с фиксированным бюджетом 2.5 с различаются на те же 0.5 с
            rig.journal.hold_stop_s = 0.5
            started = time.monotonic()
            bounded(lambda: plugin.shutdown(ctx), 10.0)
            elapsed = time.monotonic() - started
            # Предел О8 (3.0 с) действует только при survivors == []; здесь предел _S9_LIMIT_S (см. константу)
            assert elapsed <= _S9_LIMIT_S, f"plugin.shutdown() занял {elapsed:.2f} с"
            reports = _scope_reports(ctx)
            assert len(reports) == 1, [c.kwargs for c in ctx.health.report_error.call_args_list]
            survivors = reports[0].kwargs["survivors"]
            assert len(survivors) == 1 and survivors[0].startswith("device_hub/r1-prog-"), survivors
            published = [c.args for c in ctx.state_proxy.merge.call_args_list]
            assert ("devices.state.r1.last_error", _TEXT_SURVIVED) in published, published[-5:]
    finally:
        done_evt.set()
        if plugin is not None:
            _shutdown_quietly(plugin, ctx)


# --------------------------------------------------------------------------------------------------
# S10 — logger.exception в _on_shutdown
# --------------------------------------------------------------------------------------------------


def test_s10_manager_shutdown_logs_disconnect_failure_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    calls: list[str] = []

    class Boom:
        def disconnect(self) -> None:
            calls.append("boom")
            raise RuntimeError("t")

    class Fine:
        def disconnect(self) -> None:
            calls.append("fine")

    mgr = DeviceManager(store=None)
    for dev_id in ("a", "b"):
        mgr.upsert({"id": dev_id, "name": dev_id, "kind": "robot", "protocol": "delta_v2", "transport": _transport(1)})
    mgr._drivers["a"] = Boom()
    mgr._drivers["b"] = Fine()
    mgr.shutdown()
    assert calls == ["boom", "fine"]
    assert any(r.exc_info is not None and "'a'" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


# --------------------------------------------------------------------------------------------------
# S11 — HARD в фазе 1
# --------------------------------------------------------------------------------------------------


def test_s11_phase1_hard_stops_long_move_within_window(tmp_path: Path) -> None:
    # Одиночная запись сценария sim исполняет мгновенно (done за 0.03 с, замер автора); при P_SPD_J=4 каждая нога
    # из двух ~3.1 с (замер на E2eRig): SOFT посреди ноги ждал бы её конца и вышел бы за окно 3.0 с
    program = Program(name="slow", steps=(Move(point="a", kind="JOINT"), Move(point="b", kind="JOINT")))
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    plugin = ctx = None
    try:
        with E2eRig() as rig:
            plugin, ctx = _plugin_with_robots(tmp_path, {"r1": rig.port}, params={"robot_params": {"P_SPD_J": 4}})
            drv = plugin._manager.get_driver("r1")
            res = bounded(lambda: drv.start_program(program, points, None, name="slow"), _CALL_DEADLINE_S)
            assert res["status"] == "ok", res
            _until(lambda: _moving(rig.core) == 1, 5.0, "ход идёт")
            time.sleep(0.3)
            assert _moving(rig.core) == 1, "ход закончился до shutdown: программа слишком короткая"
            started = time.monotonic()
            bounded(lambda: plugin.shutdown(ctx), 10.0)
            assert time.monotonic() - started <= 3.0
            states = [
                c.args[1] for c in ctx.state_proxy.merge.call_args_list if c.args[0] == "devices.state.r1.program"
            ]
            assert states and states[-1]["state"] == "aborted", states[-3:]
            assert _scope_reports(ctx) == []
    finally:
        if plugin is not None:
            _shutdown_quietly(plugin, ctx)


# --------------------------------------------------------------------------------------------------
# S12 — _stopping и защёлка _shutdown
# --------------------------------------------------------------------------------------------------


def test_s12_stopping_and_shutdown_latch() -> None:
    _s12_part_request_stop()
    _s12_part_plain_disconnect()


def _s12_part_request_stop() -> None:
    stopping = {"status": "error", "message": _TEXT_STOPPING}
    with _bench() as (drv, rig, _rec, _scope):
        core = rig.core
        drv.request_stop()
        n_events = len(core.events())
        assert drv.call("jog_hold", _JOG) == stopping
        assert _start(drv, 4, "p12") == stopping
        started = time.monotonic()
        assert drv.connect() is False
        assert time.monotonic() - started <= 0.05, "connect() после request_stop() ходил по проводу"
        assert len(core.events()) == n_events, "после request_stop() в sim пришли новые команды"
        assert drv.call("jog_hold", _JOG) == stopping


def _s12_part_plain_disconnect() -> None:
    with _bench() as (drv, _rig, _rec, _scope):
        bounded(drv.disconnect, _CALL_DEADLINE_S)
        assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True
        assert drv.call("jog_hold", _JOG)["status"] == "ok"
        assert drv.call("jog_release", {})["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# S13 — tick_loop прерывается событием
# --------------------------------------------------------------------------------------------------


def test_s13_tick_loop_wakes_on_stop_event(tmp_path: Path) -> None:
    registry_file = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry_file)}, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    try:
        driver = type("Drv", (), {})()
        driver.entry = type("Entry", (), {"params": {"poll_interval_s": 2.0}})()
        driver.tick = lambda _stop: None
        driver.is_connected = False
        driver.reconnect_exhausted = False
        driver.last_io = None
        driver.stats = {}
        plugin._manager._drivers["r1"] = driver
        plugin._desired_connected["r1"] = True
        plugin._ensure_device_workers()
        tick_loop = ctx.worker_manager.workers["dev_r1"]["fn"]
        stop_evt, pause_evt = threading.Event(), threading.Event()
        thread = threading.Thread(target=tick_loop, args=(stop_evt, pause_evt), daemon=True)
        thread.start()
        time.sleep(0.3)
        t_set = time.monotonic()
        stop_evt.set()
        thread.join(3.0)
        assert not thread.is_alive()
        assert time.monotonic() - t_set <= 0.5
    finally:
        plugin._manager._drivers.pop("r1", None)  # у фейка нет записи реестра: disconnect шума не даёт
        _shutdown_quietly(plugin, ctx)


# --------------------------------------------------------------------------------------------------
# S14 — выживший обычного отключения доходит до health
# --------------------------------------------------------------------------------------------------


def test_s14_survivor_of_plain_disconnect_reaches_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(robot_driver_v2, "_PROGRAM_JOIN_S", 0.3)
    done_evt = threading.Event()
    plugin = ctx = None
    try:
        with E2eRig() as rig:
            plugin, ctx = _plugin_with_robots(tmp_path, {"r1": rig.port})
            drv = plugin._manager.get_driver("r1")
            drv._client.run_chunks = _fake_run_chunks(done_evt)
            assert _start(drv, 4, "p14")["status"] == "ok"
            _until(lambda: drv._prog_alive, 5.0, "исполнитель запущен")
            bounded(lambda: plugin._manager.disconnect("r1"), _CALL_DEADLINE_S)
            reports = _scope_reports(ctx)
            assert len(reports) == 1, [c.kwargs for c in ctx.health.report_error.call_args_list]
            survivors = reports[0].kwargs["survivors"]
            assert len(survivors) == 1 and survivors[0].startswith("device_hub/r1-prog-"), survivors
    finally:
        done_evt.set()
        if plugin is not None:
            _shutdown_quietly(plugin, ctx)


# --------------------------------------------------------------------------------------------------
# S15 — supervisor после shutdown
# --------------------------------------------------------------------------------------------------


def test_s15_supervisor_does_nothing_after_shutdown(tmp_path: Path) -> None:
    plugin = ctx = None
    try:
        with E2eRig() as rig:
            plugin, ctx = _plugin_with_robots(tmp_path, {"r1": rig.port})
            plugin._desired_connected["r1"] = True
            plugin._ensure_device_workers()
            assert any(n.startswith("dev_") for n in ctx.worker_manager.workers), "воркер до shutdown не создан"
            bounded(lambda: plugin.shutdown(ctx), 10.0)

            plugin._ensure_device_workers()
            assert not [n for n in ctx.worker_manager.workers if n.startswith("dev_")], ctx.worker_manager.workers
            plugin._conn_queue.put(("connect", "r1"))
            plugin._process_conn_queue()
            assert plugin._conn_queue.qsize() == 1, "supervisor разобрал очередь connect после shutdown"
    finally:
        if plugin is not None:
            _shutdown_quietly(plugin, ctx)


# --------------------------------------------------------------------------------------------------
# S16 — микроокно _program_loop: повтор стопа в on_progress
# --------------------------------------------------------------------------------------------------


def test_s16_stop_between_stopping_check_and_run_chunks_still_aborts() -> None:
    with _bench() as (drv, rig, rec, _scope):
        client = drv._client
        real = client.run_chunks

        def run_chunks(*a: Any, **k: Any) -> Any:
            drv.request_stop()  # из потока исполнителя, после проверки _stopping в _program_loop
            # Стоп обработан простым роботом ДО g0 прогона (эхо пришло): иначе робот оборвал бы сам SC_RUN, и тест
            # не зависел бы от повтора стопа в on_progress (диагноз a-I28)
            _until(lambda: rig.read("TLM_STOP_ACK")[0] != 0, 1.0, "эхо стопа до запуска прогона")
            return real(*a, **k)

        client.run_chunks = run_chunks  # type: ignore[method-assign]
        started = time.monotonic()
        assert _start(drv, 20, "p16")["status"] == "ok"  # ~5.4 с sim
        _until(
            lambda: bool(rec.programs("r1")) and rec.programs("r1")[-1][1] == "aborted",
            max(0.0, 1.0 - (time.monotonic() - started)),
            "последняя публикация .program — aborted",
        )
        _until(lambda: _moving(rig.core) == 0, 1.0, "sim: moving == 0")
