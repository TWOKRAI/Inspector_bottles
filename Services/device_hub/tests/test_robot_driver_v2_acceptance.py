"""Слепая приёмка T5.1: ``RobotDriverV2`` против sim v2 (plans/robot-protocol-v2/tasks/T5.1.md).

Purpose:
    Десять приёмочных тестов из брифа «красные тестера 1–5» и «6–10». Стенд — ``E2eRig`` из
    ``Services.robot_comm.tests.e2e_rig_v2`` (sim v2 на свободном порту, ``RecordingCore``); драйвер —
    второй клиент того же sim. Проверяется наблюдаемый эффект: регистры sim, строки событий и тики sim
    (``Tick.t`` — время sim), публикации ``publish_cb``. Спай на имя метода нигде не стоит.

Public API:
    Только тесты ``test_*``. Драйвер берётся из публичной поверхности: ``RobotDriverV2(entry, protocol,
    publish=...)``, ``call(op, args)``, ``start_program`` / ``start_return`` / ``start_toolchange``,
    ``connect`` / ``disconnect`` / ``tick`` / ``is_connected`` / ``desired_connected`` / ``transport``.

Stability: lite

Модуль драйвера импортируется внутри фикстуры или тела теста: сборка не падает, каждый тест краснеет сам.
Блокирующие вызовы идут через ``bounded`` (daemon-поток + дедлайн) — тест падает, набор не висит.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, RecordingCore, Tick, bounded, free_port, pulse

# --------------------------------------------------------------------------------------------------
# Литералы брифа
# --------------------------------------------------------------------------------------------------

HOME_POSE = (300.0, -210.0, -40.0, -100.0)
TEXT_WDG = "Пропала связь с ПК — лента и движение остановлены"
TEXT_JOG_LOST = "поводок jog прерван: нет связи с роботом"
TEXT_ABORTED = "Движение прервано стопом"
BUSY_PROGRAM = {"status": "error", "message": "робот занят программой"}
BUSY_JOG = {"status": "error", "message": "робот в режиме jog"}

_JOG = {"dir": 1, "spd": 20}
_CALL_DEADLINE_S = 15.0  # любой вызов драйвера, который может блокироваться
_CONNECT_DEADLINE_S = 60.0  # connect включает sync_params (58 записей PARAM_SET)

_CMD_JOG = re.compile(r"\[v2\] CMD seq=(\d+) op=JOG_CONT")


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


class Rec:
    """``publish_cb``: копит ``(path, payload)`` под замком."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self._items.append((path, payload))

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self._items)

    def at(self, dev_id: str, leaf: str) -> list[Any]:
        """Все полезные нагрузки по ``devices.state.<id>.<leaf>``, по порядку."""
        path = f"devices.state.{dev_id}.{leaf}"
        return [payload for p, payload in self.items() if p == path]

    def program_states(self, dev_id: str) -> list[str]:
        return [p["state"] for p in self.at(dev_id, "program") if isinstance(p, dict) and "state" in p]


def _entry(dev_id: str, port: int, **params: Any) -> DeviceEntry:
    return DeviceEntry(
        id=dev_id,
        name=dev_id,
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
        params=params,
    )


def _make(rec: Rec, dev_id: str, port: int, **params: Any) -> Any:
    """``RobotDriverV2`` без подключения. Модуль импортируется здесь (не на уровне файла)."""
    from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

    return RobotDriverV2(_entry(dev_id, port, **params), None, publish=rec)


def _tick_fn(drv: Any) -> Callable[[], object]:
    return lambda: drv.tick(None)


@contextmanager
def _connected(rec: Rec, dev_id: str, port: int, **params: Any) -> Iterator[Any]:
    """Драйвер после ``connect()`` (обязан вернуть ``True``) и ``desired_connected = True`` (НР-1)."""
    drv = _make(rec, dev_id, port, **params)
    try:
        assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True, "connect() не вернул True"
        drv.desired_connected = True
        yield drv
    finally:
        try:
            bounded(drv.disconnect, _CALL_DEADLINE_S)
        except Exception:  # noqa: BLE001 — уборка не должна подменять исключение теста
            pass


def _call(drv: Any, op: str, args: dict | None = None) -> dict:
    return bounded(lambda: drv.call(op, dict(args or {})), _CALL_DEADLINE_S)


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while True:
        if pred():
            return
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.02)


def _confirm(fn: Callable[[], object], duration_s: float, *, tolerate: bool = False, period_s: float = 0.05) -> None:
    """Звать ``fn()`` каждые ``period_s`` в течение ``duration_s`` (подтверждения удержания GUI).

    ``tolerate`` — исключения вызова (но не дедлайн) глотаются: после обрыва связи ответ не проверяется.
    """
    end = time.monotonic() + duration_s
    while time.monotonic() < end:
        started = time.monotonic()
        try:
            bounded(fn, _CALL_DEADLINE_S)
        except TimeoutError:
            raise
        except Exception:  # noqa: BLE001
            if not tolerate:
                raise
        time.sleep(max(0.0, period_s - (time.monotonic() - started)))


def _last_t(core: RecordingCore) -> float:
    return core.ticks()[-1].t


def _wait_sim(core: RecordingCore, until_t: float, timeout_s: float = 20.0) -> None:
    """Дождаться тика sim с ``t >= until_t``."""
    end = time.monotonic() + timeout_s
    while _last_t(core) < until_t:
        if time.monotonic() >= end:
            raise AssertionError(f"время sim не дошло до {until_t}")
        time.sleep(0.01)


def _first_tick(core: RecordingCore, pred: Callable[[Tick], bool], *, timeout_s: float = 10.0) -> Tick:
    end = time.monotonic() + timeout_s
    seen = 0
    while True:
        ticks = core.ticks()
        for tick in ticks[seen:]:
            if pred(tick):
                return tick
        seen = len(ticks)
        if time.monotonic() >= end:
            raise AssertionError("тик с нужным условием не появился")
        time.sleep(0.005)


def _lease_change_times(ticks: list[Tick]) -> list[float]:
    """``t`` тиков, в которых ``JOG_LEASE`` отличается от предыдущего тика."""
    out: list[float] = []
    for prev, cur in zip(ticks, ticks[1:], strict=False):
        if cur.jog_lease != prev.jog_lease:
            out.append(cur.t)
    return out


def _jog_cmd_seqs(core: RecordingCore) -> list[int]:
    return [int(m.group(1)) for _, text in core.events() if (m := _CMD_JOG.search(text))]


def _event_texts(core: RecordingCore) -> list[str]:
    return [text for _, text in core.events()]


def _legs_program(name: str, legs: int) -> tuple[Program, dict[str, Point]]:
    """``legs`` ходов JOINT между двумя точками (дом -> a -> дом -> ...); одна нога ~0.27 с sim."""
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    steps = tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(legs))
    return Program(name=name, steps=steps), points


def _start(drv: Any, program: Program, points: dict[str, Point], name: str) -> dict:
    return bounded(lambda: drv.start_program(program, points, None, name=name), _CALL_DEADLINE_S)


def _wait_program(rec: Rec, dev_id: str, state: str, deadline_s: float = 40.0) -> dict:
    """Дождаться ``.program`` с ``state``; вернуть эту публикацию."""

    def last() -> dict | None:
        items = [p for p in rec.at(dev_id, "program") if isinstance(p, dict)]
        return items[-1] if items else None

    _until(lambda: (last() or {}).get("state") == state, deadline_s, f"{dev_id}.program.state == {state!r}")
    return last()  # type: ignore[return-value]


# --------------------------------------------------------------------------------------------------
# REDS 1
# --------------------------------------------------------------------------------------------------


def test_factory_selects_driver_by_protocol() -> None:
    from Services.device_hub.drivers.robot_driver import RobotDriver

    rec = Rec()
    mgr = DeviceManager(store=None, publish_cb=rec)
    with E2eRig() as rig:
        mgr.upsert(
            {
                "id": "rob_v2",
                "name": "rob_v2",
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            }
        )
        mgr.upsert(
            {
                "id": "rob_v1",
                "name": "rob_v1",
                "kind": "robot",
                "protocol": "delta_universal3",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": free_port(), "unit_id": 1},
            }
        )
        try:
            bounded(lambda: mgr.connect("rob_v2"), _CONNECT_DEADLINE_S)
            bounded(lambda: mgr.connect("rob_v1"), _CONNECT_DEADLINE_S)  # сервера нет: False, не исключение
            drv_v2 = mgr.get_driver("rob_v2")
            drv_v1 = mgr.get_driver("rob_v1")
            from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

            assert isinstance(drv_v2, RobotDriverV2)
            assert isinstance(drv_v1, RobotDriver)
            assert not isinstance(drv_v1, RobotDriverV2)
            assert not isinstance(drv_v2, RobotDriver)
        finally:
            for dev_id in ("rob_v2", "rob_v1"):
                try:
                    bounded(lambda d=dev_id: mgr.disconnect(d), _CALL_DEADLINE_S)
                except Exception:  # noqa: BLE001 — уборка
                    pass


# --------------------------------------------------------------------------------------------------
# REDS 2
# --------------------------------------------------------------------------------------------------


def test_two_robots_do_not_share_state() -> None:
    rec = Rec()
    mgr = DeviceManager(store=None, publish_cb=rec)
    with E2eRig() as rig_a, E2eRig() as rig_b:
        for dev_id, rig in (("rob_a", rig_a), ("rob_b", rig_b)):
            mgr.upsert(
                {
                    "id": dev_id,
                    "name": dev_id,
                    "kind": "robot",
                    "protocol": "delta_v2",
                    "transport": {"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
                }
            )
        try:
            for dev_id in ("rob_a", "rob_b"):
                assert bounded(lambda d=dev_id: mgr.connect(d), _CONNECT_DEADLINE_S) is True
                mgr.get_driver(dev_id).desired_connected = True
            drv_a, drv_b = mgr.get_driver("rob_a"), mgr.get_driver("rob_b")
            with pulse(_tick_fn(drv_a), 0.1), pulse(_tick_fn(drv_b), 0.1):
                # --- программы: A (8 ходов) и одновременно B (6 ходов) ---
                prog_a, pts_a = _legs_program("prog_a", 8)
                prog_b, pts_b = _legs_program("prog_b", 6)
                assert _start(drv_a, prog_a, pts_a, "prog_a").get("status") != "error"
                assert _start(drv_b, prog_b, pts_b, "prog_b").get("status") != "error"
                final_a = _wait_program(rec, "rob_a", "done")
                final_b = _wait_program(rec, "rob_b", "done")
                assert final_a["done"] == final_a["total"]
                assert final_b["done"] == final_b["total"]
                assert final_a["name"] == "prog_a"
                assert final_b["name"] == "prog_b"
                # каждая публикация .program под своим id несёт только своё имя
                assert {p["name"] for p in rec.at("rob_a", "program")} == {"prog_a"}
                assert {p["name"] for p in rec.at("rob_b", "program")} == {"prog_b"}
                for rig in (rig_a, rig_b):  # программа действительно шла >= 1 с sim
                    starts = [stamp for stamp, text in rig.core.events() if "[v2] SC start" in text]
                    ends = [stamp for stamp, text in rig.core.events() if "[v2] SC end" in text]
                    assert starts and ends and ends[-1] - starts[0] >= 1.0

                # --- jog на обоих, подтверждения прекращены только для B ---
                assert _call(drv_a, "jog_hold", _JOG)["status"] == "ok"
                assert _call(drv_b, "jog_hold", _JOG)["status"] == "ok"
                _confirm(lambda: (drv_a.call("jog_hold", dict(_JOG)), drv_b.call("jog_hold", dict(_JOG))), 0.5)
                assert rig_a.core.ticks()[-1].moving == 1
                assert rig_b.core.ticks()[-1].moving == 1
                _confirm(lambda: drv_a.call("jog_hold", dict(_JOG)), 1.0)
                assert rig_b.core.ticks()[-1].moving == 0, "B перестал получать подтверждения, но движется"
                assert rig_a.core.ticks()[-1].moving == 1, "A подтверждается, но остановился"

                # --- телеметрия каждого = поза своего sim ---
                assert _call(drv_a, "jog_release")["status"] == "ok"
                t_after = max(_last_t(rig_a.core), _last_t(rig_b.core)) + 0.3
                _wait_sim(rig_a.core, t_after)
                _wait_sim(rig_b.core, t_after)
                assert rig_a.core.ticks()[-1].moving == 0
                for dev_id, drv, rig in (("rob_a", drv_a, rig_a), ("rob_b", drv_b, rig_b)):
                    tele = _call(drv, "get_telemetry")["telemetry"]
                    pose = rig.pose_wire()
                    got = (tele["x_mm"], tele["y_mm"], tele["z_mm"], tele["rz_deg"])
                    assert got == pytest.approx(pose, abs=0.05), f"{dev_id}: телеметрия не равна позе своего sim"
                pose_a, pose_b = rig_a.pose_wire(), rig_b.pose_wire()
                assert abs(pose_a[0] - pose_b[0]) > 5.0, "позы A и B совпали: тест ничего не различает"
        finally:
            for dev_id in ("rob_a", "rob_b"):
                try:
                    bounded(lambda d=dev_id: mgr.disconnect(d), _CALL_DEADLINE_S)
                except Exception:  # noqa: BLE001 — уборка
                    pass


# --------------------------------------------------------------------------------------------------
# REDS 3
# --------------------------------------------------------------------------------------------------


def test_get_telemetry_keys_match_v1() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv, pulse(_tick_fn(drv), 0.1):
        first = _call(drv, "get_telemetry")
        assert set(first) == {"status", "telemetry", "free", "encoder", "queue_len"}
        assert set(first["telemetry"]) == {
            "x_mm",
            "y_mm",
            "z_mm",
            "rz_deg",
            "moving",
            "spd_pct",
            "belt_mm_s",
            "heartbeat",
            "servo",
            "hand",
            "miss_count",
        }
        assert first["status"] == "ok"
        tele = first["telemetry"]
        assert (tele["x_mm"], tele["y_mm"], tele["z_mm"], tele["rz_deg"]) == pytest.approx(HOME_POSE, abs=0.05)
        assert tele["moving"] is False
        assert tele["servo"] is True
        assert first["free"] is True
        assert tele["hand"] == 1
        assert tele["miss_count"] == 0
        assert tele["spd_pct"] == 80
        assert isinstance(first["encoder"], int)
        assert first["queue_len"] == 0

        n_before = len(rig.core.ticks())
        _until(lambda: len(rig.core.ticks()) >= n_before + 2, 10.0, "sim сделал >= 2 тика")
        second = _call(drv, "get_telemetry")
        assert second["telemetry"]["heartbeat"] > first["telemetry"]["heartbeat"]


# --------------------------------------------------------------------------------------------------
# REDS 4
# --------------------------------------------------------------------------------------------------


def test_jog_stops_after_hold_lost() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv, pulse(_tick_fn(drv), 0.1):
        core = rig.core

        # --- фаза 1: подтверждения прекращены (потеря удержания) ---
        mark = len(core.ticks())
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _confirm(lambda: drv.call("jog_hold", dict(_JOG)), 1.0)
        assert core.ticks()[-1].moving == 1, "после 1.0 с удержания робот не движется: поводок не писался"
        t_conf = _last_t(core)
        seqs = _jog_cmd_seqs(core)
        assert len(seqs) == 1
        seq = seqs[0]

        stop_tick = _first_tick(core, lambda tk: tk.t > t_conf and tk.moving == 0)
        _wait_sim(core, stop_tick.t + 0.4)
        changes = _lease_change_times(core.ticks()[mark:])
        assert changes, "JOG_LEASE ни разу не менялся"
        assert changes[-1] <= t_conf + 0.35, "поводок пишется дольше окна удержания"
        assert stop_tick.t <= changes[-1] + 0.300 + stop_tick.dt
        texts = _event_texts(core)
        assert any(f"[v2] ERR seq={seq} errno=13" in text for text in texts), "стоп драйвера (Д3) не оборвал jog"
        assert not any(f"[v2] DONE seq={seq} " in text for text in texts)

        # новый jog_hold стартует чисто
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _confirm(lambda: drv.call("jog_hold", dict(_JOG)), 0.4)
        assert core.ticks()[-1].moving == 1, "новый jog_hold после истечения окна не двигает робот"
        assert len(_jog_cmd_seqs(core)) == 2
        t_rel = _last_t(core)
        assert _call(drv, "jog_release")["status"] == "ok"
        _first_tick(core, lambda tk: tk.t > t_rel and tk.moving == 0)

        # --- фаза 2: обрыв связи ---
        mark = len(core.ticks())
        n_cmd = len(_jog_cmd_seqs(core))
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _confirm(lambda: drv.call("jog_hold", dict(_JOG)), 0.5)
        bounded(drv.transport.disconnect, _CALL_DEADLINE_S)
        t_cut = _last_t(core)
        # Подтверждения GUI идут, пока канал мёртв. Драйвер может переподключиться раньше, чем кончатся 0.5 с
        # (первый реконнект v1 не ждёт порога) — тогда подтверждение само начало бы новый jog: его не шлём.
        _confirm(lambda: None if drv.transport.is_connected else drv.call("jog_hold", dict(_JOG)), 0.5, tolerate=True)
        seqs = _jog_cmd_seqs(core)
        assert len(seqs) == n_cmd + 1
        seq = seqs[-1]

        stop_tick = _first_tick(core, lambda tk: tk.t > t_cut and tk.moving == 0)
        _wait_sim(core, stop_tick.t + 0.4)
        changes = _lease_change_times(core.ticks()[mark:])
        assert changes, "JOG_LEASE ни разу не менялся"
        assert changes[-1] <= t_cut + 0.1, "поводок пишется после обрыва связи"
        texts = _event_texts(core)
        assert any(f"[v2] DONE seq={seq} op=JOG_CONT" in text for text in texts), "стоп должна дать прошивка по поводку"
        assert not any(f"[v2] ERR seq={seq}" in text for text in texts)
        assert stop_tick.t <= changes[-1] + 0.300 + stop_tick.dt
        assert TEXT_JOG_LOST in rec.at("rv2", "last_error")

        # связь восстановлена тиком (НР-1), новый jog работает
        _until(lambda: drv.is_connected and drv.transport.is_connected, 10.0, "драйвер переподключился")
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _confirm(lambda: drv.call("jog_hold", dict(_JOG)), 0.4)
        assert len(_jog_cmd_seqs(core)) == n_cmd + 2, "после переподключения нет новой строки CMD JOG_CONT"
        assert core.ticks()[-1].moving == 1
        assert _call(drv, "jog_release")["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# REDS 5
# --------------------------------------------------------------------------------------------------


def test_jog_release_stops_explicitly() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv, pulse(_tick_fn(drv), 0.1):
        core = rig.core
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        _confirm(lambda: drv.call("jog_hold", dict(_JOG)), 0.5)
        assert core.ticks()[-1].moving == 1
        seq = _jog_cmd_seqs(core)[-1]

        t_rel = _last_t(core)
        assert _call(drv, "jog_release")["status"] == "ok"
        stop_tick = _first_tick(core, lambda tk: tk.t > t_rel and tk.moving == 0)
        assert stop_tick.t <= t_rel + 0.15
        texts = _event_texts(core)
        assert any(f"[v2] ERR seq={seq} errno=13 E_ABORTED" in text for text in texts)
        assert not any(f"[v2] DONE seq={seq} " in text for text in texts)

        # свой стоп ожидаем: тик успевает опросить события, last_error молчит (Д1)
        _wait_sim(core, stop_tick.t + 0.8)
        time.sleep(0.3)
        assert [p for p in rec.at("rv2", "last_error") if TEXT_ABORTED in str(p)] == []

        # контроль: release без активного jog во время программы не шлёт стоп
        program, points = _legs_program("ctl", 8)
        assert _start(drv, program, points, "ctl").get("status") != "error"
        _until(lambda: "running" in rec.program_states("rv2"), 10.0, "программа перешла в running")
        stop_req = rig.read("STOP_REQ")
        stop_ack = rig.read("TLM_STOP_ACK")
        assert _call(drv, "jog_release") == {"status": "ok"}
        assert rig.read("STOP_REQ") == stop_req
        assert rig.read("TLM_STOP_ACK") == stop_ack
        assert _wait_program(rec, "rv2", "done")["done"] > 0
        assert rec.program_states("rv2")[-1] == "done"


# --------------------------------------------------------------------------------------------------
# REDS 6
# --------------------------------------------------------------------------------------------------


def test_restart_with_new_epoch_resends_params() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port, config_epoch=7) as drv, pulse(_tick_fn(drv), 0.1):
        assert rig.read("TLM_CFG_EPOCH") == [7]

        rig.restart(keep_regs=False)  # метка нового ядра 0
        core = rig.core
        _until(
            lambda: any("op=PARAM_SET" in text for text in _event_texts(core)) and rig.read("TLM_CFG_EPOCH") == [7],
            10.0,
            "после рестарта с меткой 0 параметры отправлены заново, метка 7",
        )

        # контроль: рестарт с сохранёнными регистрами (метка 7 на месте) параметров не шлёт
        rig.restart(keep_regs=True)
        core = rig.core
        first_hb = _first_tick(core, lambda tk: True).hb_pc
        _until(
            lambda: any(tk.hb_pc != first_hb for tk in core.ticks()),
            10.0,
            "драйвер переподключился и снова пишет HB_PC",
        )
        _wait_sim(core, _last_t(core) + 1.0)
        assert not any("op=PARAM_SET" in text for text in _event_texts(core))

        # метка ушла без обрыва связи (сверка в тике, не переподключение): драйвер шлёт параметры снова
        n_events = len(core.events())
        core.regs[REG["TLM_CFG_EPOCH"]] = 0
        _until(
            lambda: (
                any("op=PARAM_SET" in text for text in _event_texts(core)[n_events:])
                and rig.read("TLM_CFG_EPOCH") == [7]
            ),
            10.0,
            "сверка метки в тике: параметры отправлены заново без переподключения",
        )


# --------------------------------------------------------------------------------------------------
# REDS 7
# --------------------------------------------------------------------------------------------------


def test_round_step_from_entry_params() -> None:
    rec = Rec()
    target = Point(name="a", x=301.26, y=-210, z=-40, rz=-100, hand=1)
    program = Program(name="rs", steps=(Move(point="a", kind="JOINT"),))

    with E2eRig() as rig:
        with _connected(rec, "rv2", rig.port, round_step=0.5) as drv, pulse(_tick_fn(drv), 0.1):
            assert _start(drv, program, {"a": target}, "rs").get("status") != "error"
            _wait_program(rec, "rv2", "done")
            assert rig.pose_wire()[0] == pytest.approx(301.5, abs=0.01)

    rec2 = Rec()
    with E2eRig() as rig:
        with _connected(rec2, "rv2", rig.port) as drv, pulse(_tick_fn(drv), 0.1):
            assert _start(drv, program, {"a": target}, "rs").get("status") != "error"
            _wait_program(rec2, "rv2", "done")
            assert rig.pose_wire()[0] == pytest.approx(301.3, abs=0.01)

    with pytest.raises(ValueError):
        _make(Rec(), "rv2", 1, round_step=0.15)


# --------------------------------------------------------------------------------------------------
# REDS 8
# --------------------------------------------------------------------------------------------------


def _last_sc_rec(core: RecordingCore) -> str:
    recs = [text for text in _event_texts(core) if "[v2] SC rec" in text]
    assert recs, "ни одной строки SC rec"
    return recs[-1]


def test_return_and_toolchange_end_at_home() -> None:
    rec = Rec()
    slot = Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)
    lib = {
        "t1_over": Point(name="t1_over", x=350, y=100, z=-60, rz=0, hand=1),
        "t1_pick": Point(name="t1_pick", x=350, y=100, z=-120, rz=0, hand=1),
        "t1_exit": Point(name="t1_exit", x=400, y=100, z=-60, rz=0, hand=1),
    }
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv, pulse(_tick_fn(drv), 0.1):
        # --- возврат из слота ---
        res = bounded(lambda: drv.start_return(slot), _CALL_DEADLINE_S)
        assert res.get("status") != "error"
        final = _wait_program(rec, "rv2", "done")
        assert final["done"] == final["total"]
        assert "kind=JOINT" in _last_sc_rec(rig.core)
        assert rig.pose_wire() == pytest.approx(HOME_POSE, abs=0.1)

        # --- смена инструмента 0 -> 1 ---
        n_done = rec.program_states("rv2").count("done")
        res = bounded(lambda: drv.start_toolchange(0, 1, lib), _CALL_DEADLINE_S)
        assert res.get("status") != "error"
        _until(lambda: rec.program_states("rv2").count("done") == n_done + 1, 40.0, "второе done (toolchange)")
        final = [p for p in rec.at("rv2", "program") if p["state"] == "done"][-1]
        assert final["done"] == final["total"]
        assert "kind=JOINT" in _last_sc_rec(rig.core)
        assert rig.pose_wire() == pytest.approx(HOME_POSE, abs=0.1)

        # --- отказы ---
        program, points = _legs_program("long", 8)
        n_done = rec.program_states("rv2").count("done")
        assert _start(drv, program, points, "long").get("status") != "error"
        _until(lambda: "running" in rec.program_states("rv2")[-1:], 10.0, "программа идёт")
        assert _start(drv, program, points, "second") == BUSY_PROGRAM
        assert _call(drv, "jog_hold", _JOG)["status"] == "error"
        _until(lambda: rec.program_states("rv2").count("done") == n_done + 1, 40.0, "программа 'long' закончилась")

        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        assert _start(drv, program, points, "during_jog") == BUSY_JOG
        assert _call(drv, "jog_release")["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# REDS 9
# --------------------------------------------------------------------------------------------------


def test_heartbeat_watchdog_and_last_error() -> None:
    rec = Rec()
    params = {"poll_interval_s": 0.1, "robot_params": {"P_WDG_TIMEOUT_MS": 600}}
    with E2eRig() as rig, _connected(rec, "rv2", rig.port, **params) as drv:
        core = rig.core
        mark = len(core.ticks())
        t_start = _last_t(core)
        with pulse(_tick_fn(drv), 0.1):
            _wait_sim(core, t_start + 2.0)
        window = [tk for tk in core.ticks()[mark:] if tk.t <= t_start + 2.0]
        assert window
        assert all(tk.wdg_state != 2 for tk in window), "сторож сработал при идущем тике хаба"
        assert window[-1].wdg_state == 1, "сторож не взведён: HB_PC не менялся"

        # тик остановлен: сторож срабатывает за 0.6 + 0.1 с sim от последнего изменения HB_PC
        ticks = core.ticks()
        t_last_hb = [cur.t for prev, cur in zip(ticks, ticks[1:], strict=False) if cur.hb_pc != prev.hb_pc][-1]
        tripped = _first_tick(core, lambda tk: tk.t > t_last_hb and tk.wdg_state == 2, timeout_s=10.0)
        assert tripped.t <= t_last_hb + 0.6 + 0.1

        assert TEXT_WDG not in rec.at("rv2", "last_error")
        bounded(lambda: drv.tick(None), _CALL_DEADLINE_S)
        assert TEXT_WDG in rec.at("rv2", "last_error")


# --------------------------------------------------------------------------------------------------
# REDS 10
# --------------------------------------------------------------------------------------------------


def test_connect_sequence_on_connect_actions() -> None:
    rec = Rec()
    with E2eRig() as rig:
        bounded(lambda: rig.client.servo(False))  # sim стартует с серво (урок T3.9)
        assert rig.read("TLM_SERVO") == [0]
        drv = _make(rec, "rv2", rig.port, on_connect={"servo": True, "do": {"3": True}})
        mark = len(rig.core.events())
        try:
            assert bounded(drv.connect, _CONNECT_DEADLINE_S) is True
            assert rig.read("TLM_SERVO") == [1]
            assert rig.read("TLM_DO_MASK")[0] & 0b100 == 0b100  # DO3 = бит 2
            events = _event_texts(rig.core)[mark:]
            params_at = [i for i, text in enumerate(events) if "op=PARAM_SET" in text]
            servo_at = [i for i, text in enumerate(events) if "op=SERVO" in text]
            do_at = [i for i, text in enumerate(events) if "op=DO_SET" in text]
            assert params_at and servo_at and do_at, (len(params_at), len(servo_at), len(do_at))
            assert max(params_at) < min(servo_at)
            assert max(servo_at) < min(do_at)
        finally:
            try:
                bounded(drv.disconnect, _CALL_DEADLINE_S)
            except Exception:  # noqa: BLE001 — уборка
                pass
