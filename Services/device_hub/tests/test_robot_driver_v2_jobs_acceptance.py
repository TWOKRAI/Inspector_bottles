"""Слепая приёмка T3.7: операции ``enqueue_job`` / ``return_job`` у ``RobotDriverV2`` против sim v2.

Purpose:
    Десять приёмочных тестов из ``plans/robot-protocol-v2/tasks/T3.7.reds.md`` (раздел «REDS»). Стенд —
    ``E2eRig`` из ``Services.robot_comm.tests.e2e_rig_v2`` (настоящий sim v2 на свободном порту,
    ``RecordingCore``); драйвер ``RobotDriverV2`` — второй клиент того же sim. Проверяется наблюдаемый эффект:
    события sim (``rig.core.events()``), задания sim (``rig.core.jobs()``), регистры по проводу (``rig.read``),
    публикации ``publish_cb`` и ``snapshot()`` драйвера. Спая на имя метода нигде нет.

Public API:
    Только тесты ``test_*``. Драйвер берётся из публичной поверхности: ``RobotDriverV2(entry, None, publish=...)``,
    ``call("enqueue_job" | "return_job" | "jog_hold" | "jog_release", args)``, ``start_return``, ``snapshot()``,
    ``tick``, ``is_connected``, ``desired_connected``, ``transport``.

Stability: lite

Правила стенда (T3.7.reds.md, «Стенд и правила»):
    * Лента rig едет с первого тика (101.1 мм/с, +Y): литералы энкодера — только от ``E0 = rig.read("TLM_ENC", 2)``
      (младшее слово первым), абсолютных нет.
    * Точка забора: ``r = hypot(x, y)`` в 200..450 мм и ``y <= -150``; кольцо по умолчанию 120..500 мм.
    * Каждое блокирующее действие идёт под дедлайном (``bounded`` / daemon-поток с join).
    * Ответы ``enqueue_job`` / ``return_job`` не зависят от гонки с тиком: задания ставятся ДО запуска ``pulse``.
    * ``rig.core`` перечитывается на каждом обращении: ``rig.restart`` подменяет ядро.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope


from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import OP, REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Point
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

# --------------------------------------------------------------------------------------------------
# Литералы (params.md, protocol-spec §5-6, Services/robot_comm/README.md)
# --------------------------------------------------------------------------------------------------

BUSY_JOB = {"status": "error", "message": "робот выполняет задание"}
TEXT_ZONE_TRIP = "Объект вышел из рабочей зоны ленты"  # §6, errno 12 E_ZONE_TRIP
TEXT_WDG = "Пропала связь с ПК — лента и движение остановлены"
TEXT_BUSY_PROGRAM = "робот занят программой"

_JOG = {"dir": 1, "spd": 20}
_PICK = {"x_mm": 300.0, "y_mm": -250.0}  # r = 390.5 мм, y <= -150: внутри кольца 120..500 мм
_RETURN_A = {"x_mm": 350.0, "y_mm": -150.0, "z_mm": -90.0}
_RETURN_B = {"x_mm": 300.0, "y_mm": -150.0, "z_mm": -90.0}

# P_SPD_DEFAULT 15 %: ход CVT_JOB ~1.4 с sim вместо ~0.25 с при умолчании 80 % (замер на sim); 15 % -> 225 мм/с,
# быстрее ленты 101.1 мм/с, поэтому догон следимой точки сходится. Для тестов, где задание должно быть в пути.
_SLOW_JOB = {"P_SPD_DEFAULT": 15}

_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0  # connect включает sync_params (58 записей PARAM_SET)
_JOB_DEADLINE_S = 15.0

_CMD_CVT = re.compile(r"\[v2\] CMD seq=\d+ op=CVT_JOB")
_DONE_CVT = re.compile(r"\[v2\] DONE seq=\d+ op=CVT_JOB")
_SC_EDGE = re.compile(r"\[v2\] SC (start|end) ")


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


_SCOPE_BUDGET_S = 6.0


# Область потоков теста (T5.3 круг 2: драйвер без spawn потоков не запускает). Открывается на каждый тест,
# закрывается в teardown; выживших быть не должно.
_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2test", budget_s=_SCOPE_BUDGET_S)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


def _make(rec: Rec, dev_id: str, port: int, **params: Any) -> Any:
    """``RobotDriverV2`` без подключения. Модуль импортируется здесь (не на уровне файла)."""
    from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

    return RobotDriverV2(_entry(dev_id, port, **params), None, publish=rec, spawn=_SCOPE.spawn)


def _tick_fn(drv: Any) -> Callable[[], object]:
    return lambda: drv.tick(None)


@contextmanager
def _connected(rec: Rec, dev_id: str, port: int, **params: Any) -> Iterator[Any]:
    """Драйвер после ``connect()`` (обязан вернуть ``True``) и ``desired_connected = True``."""
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


def _snap(drv: Any) -> dict:
    return bounded(drv.snapshot, 5.0)


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while True:
        if pred():
            return
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.02)


def _settled(pred: Callable[[], object], deadline_s: float) -> bool:
    """Подождать условие без утверждения (исход, который тест не проверяет, но хвост тика должен кончиться)."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except Exception:  # noqa: BLE001 — ожидание не утверждает
            pass
        time.sleep(0.02)
    return False


def _texts(rig: E2eRig) -> list[str]:
    """Строки событий sim ТЕКУЩЕГО ядра (``rig.core`` меняется при ``restart``)."""
    return [text for _, text in rig.core.events()]


def _count(rig: E2eRig, rx: re.Pattern[str], start: int = 0) -> int:
    return sum(1 for text in _texts(rig)[start:] if rx.search(text))


def _enc(rig: E2eRig) -> int:
    """``TLM_ENC`` (DW, младшее слово первым) по проводу."""
    lo, hi = rig.read("TLM_ENC", 2)
    return lo | (hi << 16)


def _s16(word: int) -> int:
    return word - 0x10000 if word >= 0x8000 else word


def _wait_jobs(drv: Any, key: str, n: int, deadline_s: float = _JOB_DEADLINE_S) -> None:
    _until(lambda: _snap(drv)[key] >= n, deadline_s, f"snapshot[{key!r}] >= {n}")


def _job_span_s(rig: E2eRig, start: int = 0) -> float:
    """Время sim между ``CMD ... op=CVT_JOB`` и ``DONE ... op=CVT_JOB`` последнего задания (штампы тиков sim)."""
    events = rig.core.events()[start:]
    cmd = [stamp for stamp, text in events if _CMD_CVT.search(text)]
    done = [stamp for stamp, text in events if _DONE_CVT.search(text)]
    assert cmd and done, "нет пары CMD/DONE для CVT_JOB"
    return done[-1] - cmd[-1]


def _slot() -> Point:
    return Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)


# --------------------------------------------------------------------------------------------------
# REDS 1
# --------------------------------------------------------------------------------------------------


def test_enqueue_job_runs_cvt_job_on_v2() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv:
        assert _call(drv, "enqueue_job", _PICK) == {"status": "ok", "queue_len": 1}
        with pulse(_tick_fn(drv), 0.1):
            _until(lambda: len(rig.core.jobs()) >= 1, _JOB_DEADLINE_S, "sim принял и довёл задание CVT_JOB")
            _wait_jobs(drv, "jobs_done", 1)
        jobs = rig.core.jobs()
        assert len(jobs) == 1
        assert jobs[0]["x_mm"] == 300.0
        assert jobs[0]["y_mm"] == -250.0
        assert _count(rig, _CMD_CVT) == 1
        assert _count(rig, _DONE_CVT) == 1
        snap = _snap(drv)
        assert snap["jobs_sent"] == 1
        assert snap["jobs_done"] == 1
        assert snap["jobs_failed"] == 0
        assert snap["queue_len"] == 0


# --------------------------------------------------------------------------------------------------
# REDS 2
# --------------------------------------------------------------------------------------------------


def test_place_rz_is_pick_rz_plus_turn() -> None:
    rec = Rec()
    place = {"place_x": 450.0, "place_y": -300.0, "place_z": -90.0, "place_rz": 30.0}  # place_rz — доворот
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv:
        assert _call(drv, "enqueue_job", {**_PICK, **place})["status"] == "ok"
        with pulse(_tick_fn(drv), 0.1):
            _wait_jobs(drv, "jobs_done", 1)
            # P_PICK_RZ -1000 (-100 град) + доворот 30 град = -70 град = -700 (s16, шаг 0.1)
            assert _s16(rig.read("TLM_RZ")[0]) == -700
            assert _s16(rig.read("TLM_X")[0]) == 4500
            assert _s16(rig.read("TLM_Y")[0]) == -3000

            # задание без place_*: укладка по умолчанию P_PLACE_X/Y/RZ = 4500 / -3000 / -1000
            assert _call(drv, "enqueue_job", _PICK)["status"] == "ok"
            _wait_jobs(drv, "jobs_done", 2)
            assert _s16(rig.read("TLM_X")[0]) == 4500
            assert _s16(rig.read("TLM_Y")[0]) == -3000
            assert _s16(rig.read("TLM_RZ")[0]) == -1000


# --------------------------------------------------------------------------------------------------
# REDS 3
# --------------------------------------------------------------------------------------------------


def test_e_capture_given_and_read_now() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv:
        e0 = _enc(rig)
        assert _call(drv, "enqueue_job", {**_PICK, "e_capture": e0 + 345})["status"] == "ok"
        with pulse(_tick_fn(drv), 0.1):
            _wait_jobs(drv, "jobs_done", 1)
            assert rig.core.jobs()[0]["ecap"] == e0 + 345

            # без e_capture: энкодер читается в потоке вызова — между чтением до и после вызова
            before = _enc(rig)
            res = _call(drv, "enqueue_job", _PICK)
            after = _enc(rig)
            assert res["status"] == "ok"
            _wait_jobs(drv, "jobs_done", 2)
        ecap = rig.core.jobs()[1]["ecap"]
        assert before <= ecap <= after


# --------------------------------------------------------------------------------------------------
# REDS 4
# --------------------------------------------------------------------------------------------------


def test_pick_lead_mm_shifts_ecap_and_wraps_u32() -> None:
    rec = Rec()
    # 14.447 мм при P_BELT_FACTOR 14447 (x1e-5 мм/имп = 0.14447 мм/имп) = ровно 100 имп
    with E2eRig() as rig, _connected(rec, "rv2", rig.port, pick_lead_mm=14.447) as drv:
        e0 = _enc(rig)
        assert _call(drv, "enqueue_job", {**_PICK, "e_capture": e0 + 345})["status"] == "ok"
        with pulse(_tick_fn(drv), 0.1):
            _wait_jobs(drv, "jobs_done", 1)
            assert rig.core.jobs()[0]["ecap"] == e0 + 245

            # 50 - 100 = -50 по модулю 2^32 = 0xFFFFFFCE: на проводе младшее слово 0xFFCE, старшее 0xFFFF
            mark = len(rig.core.events())
            res = _call(drv, "enqueue_job", {**_PICK, "e_capture": 50})
            assert res["status"] == "ok"
            rig.wait_event(r"\[v2\] CMD seq=\d+ op=CVT_JOB", after=mark, timeout_s=_JOB_DEADLINE_S)
            # слова mailbox с CMD_SEQ: seq, опкод, argc, ARG0 (ecap lo), ARG1 (ecap hi)
            assert rig.read("CMD_SEQ", 5)[3:5] == [0xFFCE, 0xFFFF]
            # ход по такому ecap — промах и не предмет теста; тик должен успеть закончить до выхода pulse
            _settled(lambda: _snap(drv)["jobs_done"] + _snap(drv)["jobs_failed"] >= 2, _JOB_DEADLINE_S)


# --------------------------------------------------------------------------------------------------
# REDS 5
# --------------------------------------------------------------------------------------------------


def test_return_jobs_queue_and_run_as_programs() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv:
        # оба возврата ставятся до тика: длина очереди в ответе не зависит от гонки с дренажом
        first = _call(drv, "return_job", _RETURN_A)
        second = _call(drv, "return_job", _RETURN_B)
        assert first["status"] == "ok"
        assert first["return_queue_len"] == 1
        assert second["status"] == "ok"
        assert second["return_queue_len"] == 2
        with pulse(_tick_fn(drv), 0.1):
            _until(lambda: rec.program_states("rv2").count("done") == 2, 30.0, "две программы возврата дошли до done")
            _wait_jobs(drv, "returns_done", 2, 5.0)
        assert not any(TEXT_BUSY_PROGRAM in str(payload) for _, payload in rec.items())
        assert rec.program_states("rv2").count("done") == 2
        snap = _snap(drv)
        assert snap["returns_done"] == 2
        assert snap["returns_failed"] == 0
        assert snap["return_queued"] == 0


# --------------------------------------------------------------------------------------------------
# REDS 6
# --------------------------------------------------------------------------------------------------


class _CvtBarrier:
    """Барьер на записи mailbox с ``CVT_JOB``: ``entered`` — запись началась, ``release`` пускает её дальше."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()


def _install_cvt_barrier(device: Any, barrier: _CvtBarrier) -> None:
    """Обёртка над ``transaction`` настоящего ``ModbusDevice``: запись ``CMD_SEQ`` со вторым словом ``OP["CVT_JOB"]``
    взводит ``entered``, ждёт ``release`` (не дольше 5 с) и только потом идёт дальше."""
    original = device.transaction

    def transaction(ops: list[tuple]) -> bool:
        for op in ops:
            kind, address, value = op
            if kind == "wm" and address == REG["CMD_SEQ"] and len(value) > 1 and value[1] == OP["CVT_JOB"]:
                barrier.entered.set()
                barrier.release.wait(5.0)
                break
        return original(ops)

    device.transaction = transaction


def test_job_in_flight_refuses_jog_and_program() -> None:
    rec = Rec()
    barrier = _CvtBarrier()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv:
        _install_cvt_barrier(drv.transport, barrier)
        mark = len(rig.core.events())
        assert _call(drv, "enqueue_job", _PICK)["status"] == "ok"
        with pulse(_tick_fn(drv), 0.1):
            try:
                assert barrier.entered.wait(5.0), "тик не дошёл до записи CVT_JOB в mailbox"
                # окно: задание захвачено тиком, cvt_job в пути (mailbox держит замок клиента)
                jog = bounded(lambda: drv.call("jog_hold", dict(_JOG)), 1.0)
                assert jog == BUSY_JOB
                program = bounded(lambda: drv.start_return(_slot()), 1.0)
                assert program == BUSY_JOB
                texts = _texts(rig)[mark:]
                assert not any("op=JOG_CONT" in text for text in texts)
                assert not any("op=SC_RUN" in text for text in texts)
            finally:
                barrier.release.set()
            _until(lambda: _count(rig, _DONE_CVT, mark) == 1, _JOB_DEADLINE_S, "DONE op=CVT_JOB после release")
            # флаг задания снимается тиком чуть позже DONE: jog_hold снова принимается
            outcome: dict = {}

            def jog_accepted() -> bool:
                outcome["res"] = _call(drv, "jog_hold", _JOG)
                return outcome["res"].get("status") == "ok"

            _until(jog_accepted, 5.0, "jog_hold снова ok после задания")
            assert outcome["res"]["status"] == "ok"
            assert _call(drv, "jog_release")["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# REDS 7
# --------------------------------------------------------------------------------------------------


def test_job_waits_for_jog_and_program() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv, pulse(_tick_fn(drv), 0.1):
        # --- часть 1: поводок jog, подтверждения каждые 0.05 с ---
        hold = threading.Event()  # взведён - подтверждения идут
        hold.set()

        def confirm() -> None:
            while hold.is_set():
                try:
                    drv.call("jog_hold", dict(_JOG))
                except Exception:  # noqa: BLE001 — подтверждения GUI не утверждают
                    pass
                time.sleep(0.05)

        confirmer = threading.Thread(target=confirm, name="t37-confirm", daemon=True)
        assert _call(drv, "jog_hold", _JOG)["status"] == "ok"
        confirmer.start()
        try:
            mark = len(rig.core.events())
            res = _call(drv, "enqueue_job", _PICK)
            assert res["status"] == "ok"
            assert res["queue_len"] == 1
            time.sleep(0.6)
            assert _count(rig, _CMD_CVT, mark) == 0, "задание ушло при удержании jog"
            assert _snap(drv)["queue_len"] == 1
        finally:
            hold.clear()
            confirmer.join(2.0)
        assert not confirmer.is_alive()
        assert _call(drv, "jog_release")["status"] == "ok"
        _until(lambda: _count(rig, _DONE_CVT, mark) == 1, _JOB_DEADLINE_S, "DONE op=CVT_JOB после jog_release")
        _wait_jobs(drv, "jobs_done", 1, 5.0)

        # --- часть 2: программа возврата идёт - задание ждёт её конца ---
        mark = len(rig.core.events())
        assert bounded(lambda: drv.start_return(_slot()), _CALL_DEADLINE_S).get("status") != "error"
        _until(lambda: "running" in rec.program_states("rv2")[-1:], 10.0, "программа возврата перешла в running")
        res = _call(drv, "enqueue_job", _PICK)
        assert res["status"] == "ok"
        assert res["queue_len"] == 1
        cvt_at, _, _ = rig.wait_event(_CMD_CVT.pattern, after=mark, timeout_s=40.0)
        events = rig.core.events()
        edges = [(i, stamp) for i, (stamp, text) in enumerate(events) if i >= mark and _SC_EDGE.search(text)]
        assert edges, "нет строк SC start / SC end у программы возврата"
        assert max(i for i, _ in edges) < cvt_at, "CVT_JOB ушёл раньше конца программы"
        assert edges[-1][1] - edges[0][1] >= 1.0, "программа шла меньше 1 с: тест ничего не различает"
        assert "done" in rec.program_states("rv2"), "CVT_JOB ушёл раньше публикации .program done"
        _until(lambda: _count(rig, _DONE_CVT, mark) == 1, _JOB_DEADLINE_S, "DONE op=CVT_JOB после программы")
        _wait_jobs(drv, "jobs_done", 2, 5.0)


# --------------------------------------------------------------------------------------------------
# REDS 8
# --------------------------------------------------------------------------------------------------


def test_heartbeat_continues_during_job() -> None:
    rec = Rec()
    params = {"poll_interval_s": 0.1, "robot_params": {"P_WDG_TIMEOUT_MS": 600, **_SLOW_JOB}}
    with E2eRig() as rig, _connected(rec, "rv2", rig.port, **params) as drv:
        mark = len(rig.core.ticks())
        mark_events = len(rig.core.events())
        assert _call(drv, "enqueue_job", _PICK)["status"] == "ok"
        with pulse(_tick_fn(drv), 0.1):
            _wait_jobs(drv, "jobs_done", 1)
        # ход длиннее таймаута сторожа 0.6 с: без пульса в wait_done сторож сработал бы
        assert _job_span_s(rig, mark_events) >= 1.0, "ход короче 1 с: тест ничего не различает"
        assert not any("E_WDG_TIMEOUT" in text for text in _texts(rig))
        assert all(tk.wdg_state != 2 for tk in rig.core.ticks()[mark:]), "сторож сработал во время задания"
        assert TEXT_WDG not in rec.at("rv2", "last_error")
        snap = _snap(drv)
        assert snap["jobs_done"] == 1
        assert snap["jobs_failed"] == 0


# --------------------------------------------------------------------------------------------------
# REDS 9
# --------------------------------------------------------------------------------------------------


def test_zone_trip_fails_job_and_queue_goes_on() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port) as drv:
        # r = 50 мм < P_ZONE_MIN 120 мм: промах на тике приёма -> async E_ZONE_TRIP
        assert _call(drv, "enqueue_job", {"x_mm": 0.0, "y_mm": -50.0})["status"] == "ok"
        with pulse(_tick_fn(drv), 0.1):
            _wait_jobs(drv, "jobs_failed", 1)
            snap = _snap(drv)
            assert snap["jobs_failed"] == 1
            assert snap["jobs_done"] == 0
            assert any("E_ZONE_TRIP" in text for text in _texts(rig))
            published = rec.at("rv2", "last_error")
            assert published, "last_error не опубликован"
            assert published[-1] == TEXT_ZONE_TRIP

            # очередь идёт дальше: следующее допустимое задание выполняется
            assert _call(drv, "enqueue_job", _PICK)["status"] == "ok"
            _wait_jobs(drv, "jobs_done", 1)
        snap = _snap(drv)
        assert snap["jobs_done"] == 1
        assert snap["jobs_failed"] == 1


# --------------------------------------------------------------------------------------------------
# REDS 10
# --------------------------------------------------------------------------------------------------


def test_link_loss_during_job_then_reconnect() -> None:
    rec = Rec()
    with E2eRig() as rig, _connected(rec, "rv2", rig.port, robot_params=_SLOW_JOB) as drv:
        assert _call(drv, "enqueue_job", _PICK)["status"] == "ok"
        ticker = threading.Thread(target=lambda: drv.tick(None), name="t37-tick", daemon=True)
        mark = len(rig.core.events())
        ticker.start()
        rig.wait_event(_CMD_CVT.pattern, after=mark, timeout_s=_JOB_DEADLINE_S)

        rig.restart(keep_regs=False)  # sim с нуля на том же порту: у драйвера рвётся сокет посреди задания

        ticker.join(10.0)
        assert not ticker.is_alive(), "тик не вышел из задания за 10 с после обрыва связи"
        # СРАЗУ после тика, до следующего: сырой OSError ветки задания обязан закрыть связь (_link_lost)
        assert drv.is_connected is False
        snap = _snap(drv)
        assert snap["jobs_failed"] == 1
        assert snap["jobs_done"] == 0

        with pulse(_tick_fn(drv), 0.1):
            _until(lambda: drv.is_connected, 10.0, "драйвер переподключился тиком")
            assert _call(drv, "enqueue_job", _PICK)["status"] == "ok"
            _wait_jobs(drv, "jobs_done", 1, 20.0)
        snap = _snap(drv)
        assert snap["jobs_done"] == 1
        assert snap["jobs_failed"] == 1
        assert len(rig.core.jobs()) == 1  # ядро после рестарта - новое: одно задание
