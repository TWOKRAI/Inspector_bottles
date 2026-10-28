"""Слепая приёмка T5.3e.3 (бриф 3a): ``robot_park`` драйвера робота v2, А1–А18 против sim v2.

Purpose:
    Восемнадцать приёмочных тестов команды ``robot_park`` (``drv.call("park", ...)``): ответ сразу, ход «конец
    команды/цикла -> дом -> серво OFF» в тике драйвера, форма ``devices.state.<id>.park``, отказы во время park и после
    него, срок, обрыв связи, остановка и отключение. Стенд — ``RobotDriverV2(entry, clock=fake_clock.clock,
    sleep=fake_clock.sleep, publish=rec, spawn=...)`` над настоящим ``E2eRig``; тик — ``drv.tick()`` вручную. Ход sim и
    поток поводка идут реальным временем (ждём через ``bounded`` / ``_until``), окно удержания jog считают часы
    драйвера (``fake_clock.t += ...``). Сим идёт медленно (``robot_params`` ``P_SPD_DEFAULT = 10``: нога ~2 с вместо
    ~0,3 с): так ход домой гарантированно длиннее вмешательства теста. Наблюдается эффект — ответы, публикации
    ``.park`` / ``.program``, регистры sim, журнал обмена, события sim, строки лога; не имена методов.

Public API:
    Только тесты ``test_*``.

Stability: lite

Допущения теста (не из спеки, прочитаны у стенда или выбраны мной):
    * «Робот вне дома» — одна команда ``jog_step`` ``dx = 80`` (x = 380, дальше любого допуска дома).
    * Тесты, где park должен идти до конца, гонят ``drv.tick()`` каждые 0,05 с реального времени при замороженных
      часах драйвера (срок park не истекает); пошаговые А1, А2, А7, А16 тикают вручную и ровно по спеке.
    * А13 зелёный уже сейчас: отказ «не подключено» даёт сам ``DeviceManager.call`` до драйвера (см. отчёт).
Ожидаемые значения — литералы ``T5.3e.1.acceptance.md``, не вычисления по коду.
"""

from __future__ import annotations

import copy
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.robot_data import save_points, save_program
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

# --------------------------------------------------------------------------------------------------
# Литералы брифа
# --------------------------------------------------------------------------------------------------

DEV = "rpark"
TEXT_PARK_BUSY = "идёт основная остановка робота"
TEXT_NEED_SERVO = "робот остановлен: включите серво"
TEXT_BAD_ARGS = "неверные аргументы команды робота"
TEXT_STOP_BY_DRIVER = "драйвер робота останавливается"
TEXT_TIMEOUT = "срок вышел"
TEXT_LINK_LOST = "связь с роботом потеряна"
TEXT_OPERATOR_STOP = "прервано стопом оператора"
TEXT_DISCONNECTING = "идёт отключение робота"
_PARK_KEYS = {"seq", "state", "step", "home", "servo", "dropped", "reason", "elapsed_s"}
_LEASE_MARK = "jog остановлен поводком"
_LOGGER = "mpf.Services.device_hub.drivers.base"
_JOG = {"dir": 1, "spd": 20}

_CALL_S = 15.0
_CONNECT_S = 60.0
_SCOPE_BUDGET_S = 6.0
_PARK_DEADLINE_S = 40.0
_LOG_LIMIT = 2000
_SLOW_PARAMS = {"robot_params": {"P_SPD_DEFAULT": 10}}  # нога ~2 с: ход домой длиннее вмешательств теста

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2park", budget_s=_SCOPE_BUDGET_S)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


# --------------------------------------------------------------------------------------------------
# Стенд
# --------------------------------------------------------------------------------------------------


class Rec:
    """``publish``: копит ``(path, payload)`` в порядке публикации; хуки зовутся в потоке публикующего."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []
        self._hooks: list[Callable[[str, Any], None]] = []

    def __call__(self, path: str, payload: Any) -> None:
        item = copy.deepcopy(payload)
        with self._lock:
            self._items.append((path, item))
            hooks = list(self._hooks)
        for hook in hooks:
            hook(path, item)

    def hook(self, fn: Callable[[str, Any], None]) -> None:
        with self._lock:
            self._hooks.append(fn)

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self._items)

    def at(self, leaf: str) -> list[Any]:
        path = f"devices.state.{DEV}.{leaf}"
        return [payload for p, payload in self.items() if p == path]


@dataclass
class Env:
    drv: RobotDriverV2
    rig: E2eRig
    rec: Rec
    clock: FakeClock
    store: RobotDataStore | None


def _entry(port: int) -> DeviceEntry:
    return DeviceEntry(
        id=DEV,
        name=DEV,
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
        params=dict(_SLOW_PARAMS),
    )


@contextmanager
def _env(fake_clock: FakeClock, tmp_path: Path, *, with_store: bool = False) -> Iterator[Env]:
    """Подключённый драйвер над ``E2eRig``; тик не идёт (его гонит тест); уборка не подменяет исключение теста."""
    store = RobotDataStore(tmp_path / "robot") if with_store else None
    rec = Rec()
    with E2eRig() as rig:
        drv = RobotDriverV2(
            _entry(rig.port),
            clock=fake_clock.clock,
            sleep=fake_clock.sleep,
            publish=rec,
            spawn=_SCOPE.spawn,
            store=store,
        )
        assert bounded(drv.connect, _CONNECT_S) is True
        drv.desired_connected = True
        try:
            yield Env(drv, rig, rec, fake_clock, store)
        finally:
            try:
                bounded(drv.disconnect, _CALL_S)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while True:
        if pred():
            return
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались за {deadline_s} с: {what}")
        time.sleep(0.02)


def _call(e: Env, op: str, args: dict | None = None) -> dict:
    return bounded(lambda: e.drv.call(op, dict(args or {})), _CALL_S)


def _tick(e: Env) -> None:
    bounded(e.drv.tick, _CALL_S)


def _park(e: Env, args: dict | None = None) -> dict:
    """``robot_park`` принят: ``accepted is True``. Любой иной ответ — красный тест (команды park нет / отказ)."""
    reply = _call(e, "park", args)
    assert reply.get("status") == "ok" and reply.get("accepted") is True, f"park не принят: {reply}"
    return reply


def _last_park(e: Env) -> dict | None:
    values = e.rec.at("park")
    return values[-1] if values else None


def _is_terminal(value: dict | None) -> bool:
    return value is not None and value.get("state") in ("done", "failed")


def _drive(e: Env, deadline_s: float = _PARK_DEADLINE_S) -> dict:
    """Гнать ``drv.tick()`` каждые 0,05 с (часы драйвера стоят) до терминального значения ``.park``."""
    end = time.monotonic() + deadline_s
    while True:
        _tick(e)
        value = _last_park(e)
        if _is_terminal(value):
            return value  # type: ignore[return-value]
        if time.monotonic() >= end:
            raise AssertionError(f"park не дошёл до итога за {deadline_s} с: {value}")
        time.sleep(0.05)


def _programs(e: Env, name: str) -> list[dict]:
    return [p for p in e.rec.at("program") if isinstance(p, dict) and p.get("name") == name]


def _wait_program(e: Env, name: str, state: str, deadline_s: float = 30.0) -> None:
    _until(lambda: any(p.get("state") == state for p in _programs(e, name)), deadline_s, f".program {name}/{state}")


def _wait_moving(e: Env, deadline_s: float = 10.0) -> None:
    _until(lambda: e.rig.read("TLM_MOVING") == [1], deadline_s, "TLM_MOVING == 1")


def _off_home(e: Env) -> None:
    """Робот вне дома, простой: одна команда ``jog_step`` (+80 мм по X)."""
    assert _call(e, "jog_step", {"dx": 80, "dy": 0, "spd": 50})["status"] == "ok"
    _until(
        lambda: abs(e.rig.pose_wire()[0] - 380.0) <= 0.05 and e.rig.read("TLM_MOVING") == [0], 10, "x_mm == 380, стоит"
    )


def _legs_program(name: str, legs: int) -> tuple[Program, dict[str, Point]]:
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        # b не должна совпадать с P_HOME (300, -210, -40, -100): иначе после abort робот уже дома (home == already)
        "b": Point(name="b", x=300, y=210, z=-40, rz=100, hand=1),
    }
    steps = tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(legs))
    return Program(name=name, steps=steps), points


def _start_user_program(e: Env, legs: int = 4, name: str = "user_prog") -> None:
    program, points = _legs_program(name, legs)
    answer = bounded(lambda: e.drv.start_program(program, points, None, name=name), _CALL_S)
    assert answer["status"] == "ok", answer
    _wait_moving(e)


# --- журнал обмена: записи STOP_REQ (образец _StopWatcher, test_robot_v2_ops_acceptance) -------------------------

_STOP_LINE = re.compile(r"^W STOP_REQ = (\d+)$")


def _exchange(e: Env, since: int) -> dict:
    answer = bounded(lambda: e.drv.call("exchange_log_get", {"since_seq": since, "limit": _LOG_LIMIT}), _CALL_S)
    assert answer["status"] == "ok", answer
    return answer


def _log_mark(e: Env) -> int:
    return _exchange(e, 0)["last_seq"] + 1


def _stop_values(e: Env, since: int) -> list[int]:
    answer = _exchange(e, since)
    assert answer["dropped"] == 0, answer["dropped"]
    values: list[int] = []
    for line in answer["lines"]:
        match = _STOP_LINE.match(line["text"])
        if match:
            values.extend([int(match.group(1))] * line["n"])
    return values


def _levels(e: Env, since: int) -> list[int]:
    return [v & 3 for v in _stop_values(e, since)]


def _param_sets(e: Env) -> int:
    return sum(1 for _, text in e.rig.core.events() if re.search(r"op=PARAM_SET$", text))


# --------------------------------------------------------------------------------------------------
# А1–А2
# --------------------------------------------------------------------------------------------------


def test_a1_park_from_outside_home_idle(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А1: вне дома, простой. Ответ-литерал; 1-й тик — parking/home; серво OFF после хода; STOP_REQ нет."""
    with _env(fake_clock, tmp_path) as e:
        _off_home(e)
        servo_at_done: list[list[int]] = []

        def on_publish(path: str, payload: Any) -> None:
            if path.endswith(".program") and payload.get("name") == "park_home" and payload.get("state") == "done":
                servo_at_done.append(e.rig.read("TLM_SERVO"))

        e.rec.hook(on_publish)
        since = _log_mark(e)
        reply = _call(e, "park")
        assert reply == {"status": "ok", "accepted": True, "seq": 1, "timeout_s": 30.0}

        _tick(e)
        parking = _last_park(e)
        assert parking is not None
        assert (parking["seq"], parking["state"], parking["step"]) == (1, "parking", "home")

        _until(lambda: bool(_programs(e, "park_home")), 10, ".program.name == park_home")
        _wait_program(e, "park_home", "done")
        _tick(e)
        final = _last_park(e)
        assert final is not None
        assert set(final) == _PARK_KEYS
        assert (final["seq"], final["state"], final["home"], final["servo"]) == (1, "done", "moved", False)
        assert servo_at_done == [[1]]  # к моменту done программы дома серво ещё включено
        _until(lambda: e.rig.read("TLM_SERVO") == [0], 5, "TLM_SERVO == 0 после итога")
        assert _stop_values(e, since) == []  # park без jog и программы STOP_REQ не пишет


def test_a2_already_home_second_park(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А2: после А1 серво ON, второй park — дом уже достигнут: ``home == "already"``, ``.program`` не менялся."""
    with _env(fake_clock, tmp_path) as e:
        _off_home(e)
        _park(e)
        first = _drive(e)
        assert (first["state"], first["home"]) == ("done", "moved")
        assert _call(e, "servo", {"on": True})["status"] == "ok"
        _until(lambda: e.rig.read("TLM_SERVO") == [1], 5, "TLM_SERVO == 1")
        programs_before = len(e.rec.at("program"))

        _park(e)
        _tick(e)
        final = _last_park(e)
        assert final is not None
        assert (final["state"], final["home"]) == ("done", "already")
        assert len(e.rec.at("program")) == programs_before


# --------------------------------------------------------------------------------------------------
# А3
# --------------------------------------------------------------------------------------------------


class _Holder:
    """Держатель jog: ``jog_hold`` каждые ~0,05 с реального времени; ответы с временем отправки."""

    def __init__(self, e: Env) -> None:
        self._e = e
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._results: list[tuple[float, dict]] = []
        self._t_reply: float | None = None
        self._thread = threading.Thread(target=self._run, name="park-holder", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            t_send = time.monotonic()
            answer = self._e.drv.call("jog_hold", dict(_JOG))
            with self._lock:
                self._results.append((t_send, answer))
            self._stop.wait(0.05)

    def start(self) -> None:
        self._thread.start()

    def halt(self) -> None:
        self._stop.set()
        self._thread.join(_CALL_S)

    def mark_reply(self) -> None:
        with self._lock:
            self._t_reply = time.monotonic()

    def ok_count(self) -> int:
        with self._lock:
            return sum(1 for _, a in self._results if a.get("status") == "ok")

    def after_reply(self) -> list[dict]:
        with self._lock:
            return [a for t, a in self._results if self._t_reply is not None and t >= self._t_reply]


def test_a3_held_jog_is_released_once_and_holds_are_refused(
    fake_clock: FakeClock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """А3: держится jog. Ответ ≤ 1 с; одна запись SOFT до тика; строк поводка 0; jog_hold после ответа — отказы."""
    with caplog.at_level(logging.INFO, logger=_LOGGER), _env(fake_clock, tmp_path) as e:
        holder = _Holder(e)
        holder.start()
        try:
            _until(lambda: holder.ok_count() >= 1, 5, "первый ok держателя")
            _wait_moving(e)
            since = _log_mark(e)
            t0 = time.monotonic()
            reply = _park(e)
            elapsed = time.monotonic() - t0
            holder.mark_reply()
            assert elapsed <= 1.0, f"ответ park {elapsed:.3f} с"
            assert reply["seq"] == 1
            _until(lambda: len(holder.after_reply()) >= 3, 5, "≥ 3 посылки jog_hold после ответа")
            assert _levels(e, since) == [1]  # ровно одна запись, SOFT, до 1-го тика

            e.clock.t += 0.3  # окно удержания (0,2 с) по часам драйвера истекло бы
            time.sleep(0.5)
            lease_lines = [m for m in (r.getMessage() for r in caplog.records) if _LEASE_MARK in m]
            assert lease_lines == []
            after = holder.after_reply()
            assert len(after) >= 3
            for answer in after:
                assert answer["status"] == "error", answer
                assert answer["message"] in (TEXT_PARK_BUSY, TEXT_NEED_SERVO), answer
        finally:
            holder.halt()


# --------------------------------------------------------------------------------------------------
# А4–А5
# --------------------------------------------------------------------------------------------------


def test_a4_user_program_is_aborted_before_home(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А4: идёт программа пользователя (≥ 3 хода). ``aborted`` раньше ``park_home`` ``running``; итог done/moved."""
    with _env(fake_clock, tmp_path) as e:
        _start_user_program(e, legs=4)
        _park(e)
        final = _drive(e)
        assert (final["state"], final["home"]) == ("done", "moved")
        items = [p for path, p in e.rec.items() if path.endswith(".program") and isinstance(p, dict)]
        aborted = [i for i, p in enumerate(items) if p["name"] == "user_prog" and p["state"] == "aborted"]
        running = [i for i, p in enumerate(items) if p["name"] == "park_home" and p["state"] == "running"]
        assert aborted and running, items
        assert aborted[0] < running[0], items


def test_a5_refusals_after_done_until_servo_on(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А5: после done операции движения отказывают «включите серво»; ``servo on`` снимает отказ."""
    with _env(fake_clock, tmp_path, with_store=True) as e:
        program, points = _legs_program("two", 2)
        save_points(e.store, DEV, points, base_rev=None)
        save_program(e.store, DEV, program, base_rev=None)
        _off_home(e)
        _park(e)
        assert _drive(e)["state"] == "done"
        refused = {"status": "error", "message": TEXT_NEED_SERVO}
        assert _call(e, "program_run", {"name": "two"}) == refused
        assert _call(e, "jog_step", {"dx": 10, "dy": 0, "spd": 50}) == refused
        assert _call(e, "enqueue_job", {"x_mm": 300, "y_mm": -150})["message"] == TEXT_NEED_SERVO
        assert _call(e, "jog_hold", dict(_JOG)) == refused
        assert _call(e, "servo", {"on": True})["status"] == "ok"
        _until(lambda: e.rig.read("TLM_SERVO") == [1], 5, "TLM_SERVO == 1")
        assert _call(e, "jog_step", {"dx": 10, "dy": 0, "spd": 50})["status"] == "ok"


# --------------------------------------------------------------------------------------------------
# А6–А8
# --------------------------------------------------------------------------------------------------


def _start_home_move(e: Env, args: dict | None = None) -> None:
    """Вне дома, park принят, 1-й тик запустил ход домой, робот движется."""
    _off_home(e)
    _park(e, args)
    _tick(e)
    _until(lambda: bool(_programs(e, "park_home")), 10, ".program park_home")
    _wait_moving(e)


def test_a6_request_stop_during_home_move(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А6: ``request_stop()`` во время хода домой. К возврату — failed/home; HARD записан; серво не выключено."""
    with _env(fake_clock, tmp_path) as e:
        _start_home_move(e)
        since = _log_mark(e)
        at_failed: list[list[int]] = []

        def on_publish(path: str, payload: Any) -> None:
            if path.endswith(".park") and payload.get("state") == "failed":
                at_failed.append(_levels(e, since))

        e.rec.hook(on_publish)
        stopper = threading.Thread(target=lambda: e.drv.request_stop(time.monotonic() + 2.5), daemon=True)
        stopper.start()
        stopper.join(_CALL_S)
        assert not stopper.is_alive(), "request_stop не вернулся"
        final = _last_park(e)
        assert final is not None
        assert (final["state"], final["step"], final["reason"]) == ("failed", "home", TEXT_STOP_BY_DRIVER)
        assert at_failed and at_failed[0].count(2) >= 1, at_failed
        assert e.rig.read("TLM_SERVO") == [1]


def test_a7_timeout_fails_then_jog_works(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А7: ``timeout_s: 1.0`` и ход длиннее. Срок вышел -> failed; программа дома доходит до done без стопа; jog ok."""
    with _env(fake_clock, tmp_path) as e:
        _off_home(e)
        reply = _call(e, "park", {"timeout_s": 1.0})
        assert reply == {"status": "ok", "accepted": True, "seq": 1, "timeout_s": 1.0}
        _tick(e)
        _until(lambda: bool(_programs(e, "park_home")), 10, ".program park_home")
        e.clock.t += 1.1
        _tick(e)
        final = _last_park(e)
        assert final is not None
        assert (final["state"], final["reason"]) == ("failed", TEXT_TIMEOUT)
        since = _log_mark(e)
        _wait_program(e, "park_home", "done")
        assert _stop_values(e, since) == []
        assert _call(e, "jog_step", {"dx": 10, "dy": 0, "spd": 50})["status"] == "ok"


def test_a8_link_loss_during_home_move(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А8: обрыв связи (``rig.restart()``) в ходе домой: failed «связь потеряна» ≤ 2-го тика; реконнект."""
    with _env(fake_clock, tmp_path) as e:
        _start_home_move(e)
        bounded(e.rig.restart, 20.0)
        final = None
        for _ in range(2):
            time.sleep(0.3)  # поток программы успевает увидеть обрыв
            _tick(e)
            final = _last_park(e)
            if _is_terminal(final):
                break
        assert final is not None
        assert (final["state"], final["reason"]) == ("failed", TEXT_LINK_LOST)
        _until(
            lambda: all(p.get("state") != "running" for p in _programs(e, "park_home")[-1:]),
            60,
            "поток программы дома вышел",
        )
        for _ in range(3):
            e.clock.t += 2.1
            _tick(e)
            if e.drv.is_connected is True:
                break
        assert e.drv.is_connected is True


# --------------------------------------------------------------------------------------------------
# А9–А11
# --------------------------------------------------------------------------------------------------


def test_a9_held_jog_and_queued_jobs_are_dropped(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А9: держится jog, в очереди 2 задания: итог ``dropped == {jobs: 2, returns: 0}``, ``jobs_sent`` не вырос."""
    with _env(fake_clock, tmp_path) as e:
        assert _call(e, "enqueue_job", {"x_mm": 300, "y_mm": -150})["status"] == "ok"
        assert _call(e, "enqueue_job", {"x_mm": 310, "y_mm": -150})["status"] == "ok"
        assert _call(e, "jog_hold", dict(_JOG))["status"] == "ok"  # окно по часам драйвера: они стоят, jog держится
        sent_before = e.drv.jobs_sent
        _park(e)
        final = _drive(e)
        assert final["state"] == "done"
        assert final["dropped"] == {"jobs": 2, "returns": 0}
        assert e.drv.jobs_sent == sent_before


@pytest.mark.parametrize("bad", [0.5, 61, True, "30"])
def test_a10_bad_timeout_is_refused(bad: Any, fake_clock: FakeClock, tmp_path: Path) -> None:
    """А10: ``timeout_s`` 0,5; 61; True; «30» — постоянный текст, ``.park`` не появился."""
    with _env(fake_clock, tmp_path) as e:
        reply = _call(e, "park", {"timeout_s": bad})
        assert reply == {"status": "error", "message": TEXT_BAD_ARGS}
        assert e.rec.at("park") == []


def test_a11_second_park_is_refused(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А11: второй park во время хода — «идёт основная остановка робота»; итог первого — ``seq == 1``."""
    with _env(fake_clock, tmp_path) as e:
        _start_home_move(e)
        second = _call(e, "park")
        assert second["status"] == "error"
        assert second["message"] == TEXT_PARK_BUSY
        final = _drive(e)
        assert (final["seq"], final["state"]) == (1, "done")


# --------------------------------------------------------------------------------------------------
# А12
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "args"),
    [("stop", {"level": "HARD"}), ("stop", {"level": "SOFT"}), ("abort", {"mode": 1})],
    ids=["stop-HARD", "stop-SOFT", "abort-1"],
)
def test_a12_operator_stop_on_activity_step(op: str, args: dict, fake_clock: FakeClock, tmp_path: Path) -> None:
    """А12: park ждёт задание в полёте (шаг activity); стоп оператора -> failed «прервано стопом оператора»."""
    with _env(fake_clock, tmp_path) as e:
        assert _call(e, "enqueue_job", {"x_mm": 300, "y_mm": -150})["status"] == "ok"
        ticker = threading.Thread(target=e.drv.tick, name="park-job-tick", daemon=True)  # держится в wait_done
        ticker.start()
        _until(lambda: e.drv.jobs_sent >= 1, 10, "задание ушло в полёт")
        _park(e)
        assert _call(e, op, args)["status"] == "ok"
        ticker.join(30.0)
        assert not ticker.is_alive(), "тик с заданием не вернулся"
        _tick(e)
        final = _last_park(e)
        assert final is not None
        assert (final["state"], final["reason"]) == ("failed", TEXT_OPERATOR_STOP)
        assert _programs(e, "park_home") == []


# --------------------------------------------------------------------------------------------------
# А13
# --------------------------------------------------------------------------------------------------


def test_a13_refused_when_robot_not_connected(tmp_path: Path) -> None:
    """А13: робот не подключён (через ``DeviceManager``): отказ «не подключено», ``.park`` не появился."""
    rec = Rec()
    mgr = DeviceManager(store=None, publish_cb=rec, spawn=_SCOPE.spawn, robot_store=RobotDataStore(tmp_path / "robot"))
    mgr.upsert(
        {
            "id": DEV,
            "name": DEV,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": 9, "unit_id": ROBOT_UNIT_ID},
        }
    )
    reply = mgr.call(DEV, "park", {})
    assert reply["status"] == "error"
    assert "не подключено" in reply["message"]
    assert rec.at("park") == []


# --------------------------------------------------------------------------------------------------
# А14–А15
# --------------------------------------------------------------------------------------------------


def test_a14_disconnect_during_home_move(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А14: ``disconnect()`` во время хода: к возврату итог failed «идёт отключение робота»."""
    with _env(fake_clock, tmp_path) as e:
        _start_home_move(e)
        bounded(e.drv.disconnect, 30.0)
        final = _last_park(e)
        assert final is not None
        assert (final["state"], final["reason"]) == ("failed", TEXT_DISCONNECTING)


def test_a15_return_kept_in_queue_and_dropped_when_park_begins_first(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А15: park пришёл до запуска возврата, снятого тиком: возврат остался в очереди (не failed) и учтён в dropped."""
    with _env(fake_clock, tmp_path) as e:
        seen: list[dict] = []
        original = e.drv.start_return

        def start_return_after_park(slot: Point, **kw: Any) -> dict:
            seen.append(e.drv.call("park", {}))
            return original(slot, **kw)

        e.drv.start_return = start_return_after_park  # публичный шов: обёртка возврата, тиком снятого из очереди
        assert _call(e, "return_job", {"x_mm": 330.0, "y_mm": -150.0}) == {"status": "ok", "return_queue_len": 1}
        _tick(e)
        assert seen and seen[0].get("accepted") is True, seen
        final = _drive(e)
        assert final["state"] == "done"
        assert final["dropped"]["returns"] == 1
        assert e.drv.returns_failed == 0


# --------------------------------------------------------------------------------------------------
# А16–А18
# --------------------------------------------------------------------------------------------------


def test_a16_manual_connect_during_park_does_not_resync(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А16: ``connect()`` вручную во время park, связь жива: True, ни одного PARAM_SET; 1-й тик — parking/home."""
    with _env(fake_clock, tmp_path) as e:
        _off_home(e)
        _park(e)
        sets_before = _param_sets(e)
        assert bounded(e.drv.connect, _CONNECT_S) is True
        assert _param_sets(e) == sets_before
        _tick(e)
        parking = _last_park(e)
        assert parking is not None
        assert (parking["state"], parking["step"]) == ("parking", "home")


def test_a17_param_set_refused_during_park(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А17: ``param_set`` во время park — «идёт основная остановка робота», PARAM_SET в sim нет."""
    with _env(fake_clock, tmp_path, with_store=True) as e:
        _start_home_move(e)
        sets_before = _param_sets(e)
        reply = _call(e, "param_set", {"name": "P_SPD_DEFAULT", "value": 55, "base_rev": None})
        assert reply["status"] == "error"
        assert reply["message"] == TEXT_PARK_BUSY
        assert _param_sets(e) == sets_before


def test_a18_reconnect_after_done_keeps_servo_off(fake_clock: FakeClock, tmp_path: Path) -> None:
    """А18: реконнект после done: серво остаётся выключенным, ``jog_step`` отказывает «включите серво»."""
    with _env(fake_clock, tmp_path) as e:
        _off_home(e)
        _park(e)
        assert _drive(e)["state"] == "done"
        _until(lambda: e.rig.read("TLM_SERVO") == [0], 5, "TLM_SERVO == 0 после итога")
        bounded(e.rig.restart, 20.0)
        for _ in range(6):
            e.clock.t += 2.1
            _tick(e)
            if e.drv.is_connected is True:
                break
        assert e.drv.is_connected is True
        assert e.rig.read("TLM_SERVO") == [0]
        assert _call(e, "jog_step", {"dx": 10, "dy": 0, "spd": 50}) == {"status": "error", "message": TEXT_NEED_SERVO}
