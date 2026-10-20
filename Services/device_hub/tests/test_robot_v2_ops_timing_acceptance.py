"""Слепая приёмка T5.3d часть d2: гонка пересинхронизации и сроки ответов О9 (plans/robot-protocol-v2/tasks/T5.3d2.md).

Purpose:
    Четыре приёмочных теста (REDS 9, 11, 12, 15) над ``DeviceManager(store=None, publish_cb=rec,
    spawn=scope.spawn, robot_store=RobotDataStore(tmp_path / "robot"))`` и ``E2eRig`` (sim v2):

    * ``test_resync_does_not_race_commands`` (9) — детерминированный шов на ``drv._client.cmd`` держит первый
      ``PARAM_SET`` пересинхронизации по метке; команды движения и параметров в этом окне отвечают постоянным
      текстом, после окна работают, ``last_error`` о сбое синхронизации не публикуется;
    * ``test_handlers_return_within_one_second`` (11) — каждая из 15 операций возвращается не дольше 1,0 с;
    * ``test_stop_during_jog_release_answers_within_1_5s`` (12) — модель Ф8, один поток-исполнитель с очередью:
      ``jog_release``, затем ``stop``; ответ ``stop`` не позже 1,5 с от постановки;
    * ``test_stop_not_blocked_by_inflight_jog_release`` (15) — параллельная модель: ``stop`` не ждёт ``jog_release``,
      застрявший (шов 2,0 с на эхо) в записи стопа своего jog.

    Проверяется наблюдаемый эффект: ответ операции, время по ``time.monotonic()``, регистры и события sim,
    публикации ``last_error``. Ожидаемые значения — литералы брифа. Любой блокирующий вызов идёт в daemon-потоке с
    дедлайном: тест падает, набор не висит.

Public API:
    Только тесты ``test_*``. Операции d1 (``stop``, ``servo``, ``program_run`` и др.) на базе ещё не существуют:
    тесты обращаются к ним через ``DeviceManager`` / ``drv.call`` в телах, сборка проходит.

Stability: lite

Допущения теста (не из спеки, прочитаны у кода и sim):
    * ``rig.restart(keep_regs=False)`` обнуляет метку sim; драйвер переподключается тиком (``connect()`` →
      ``sync_params`` → ``_ready``). Конец переподключения — наблюдаемый: метка робота равна 1 (метка ПК по
      умолчанию), ``drv.is_connected``, ``drv.transport.is_connected``.
    * Окно удержания jog — 0,2 с (``_HOLD_WINDOW_S``): ``jog_release`` и ``jog_hold``, идущие подряд без пауз,
      видят свой jog активным.
"""

from __future__ import annotations

import queue
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

from Services.device_hub.manager import DeviceManager
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.robot_data import load_points, save_points, save_program
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

# --------------------------------------------------------------------------------------------------
# Литералы брифа
# --------------------------------------------------------------------------------------------------

DEV = "rob_v2"
SYNC_TEXT = "идёт синхронизация параметров"
SYNC_REPLY = {"status": "error", "message": SYNC_TEXT}
BUSY_PROGRAM = {"status": "error", "message": "робот занят программой"}
SYNC_FAILED_PREFIX = "синхронизация параметров не удалась"
DEFAULT_EPOCH = 1  # метка ПК при пустом хранилище (params.yaml нет)

HANDLER_LIMIT_S = 1.0  # О9: обработчик каждой robot_* возвращается не дольше
STOP_AFTER_RELEASE_LIMIT_S = 1.5  # О9: stop в очереди после jog_release
SEAM_SLEEP_S = 2.0  # шов RED 15: сон jog_release перед ожиданием эха

#: 15 операций RED 11 (9 новых d1 + abort + 5 прежних/общих).
OPS_15 = frozenset(
    {
        "stop",
        "servo",
        "do_set",
        "jog_step",
        "point_capture",
        "param_set",
        "param_apply",
        "program_run",
        "program_abort",
        "abort",
        "jog_hold",
        "jog_release",
        "get_telemetry",
        "enqueue_job",
        "return_job",
    }
)

_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0  # connect включает sync_params (десятки PARAM_SET)
_RECONNECT_DEADLINE_S = 20.0
_SCOPE_BUDGET_S = 6.0
_JOG = {"dir": 1, "spd": 20}


# --------------------------------------------------------------------------------------------------
# Область потоков теста (драйвер без spawn потоков не запускает)
# --------------------------------------------------------------------------------------------------

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2timing", budget_s=_SCOPE_BUDGET_S)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


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

    def at(self, leaf: str) -> list[Any]:
        path = f"devices.state.{DEV}.{leaf}"
        with self._lock:
            return [payload for p, payload in self._items if p == path]


@dataclass
class Hub:
    mgr: DeviceManager
    rig: E2eRig
    rec: Rec
    drv: Any
    store: RobotDataStore

    def count(self, pattern: str) -> int:
        """Сколько строк событий текущего ядра sim (на ACK) подходит под ``pattern``."""
        return sum(1 for _, text in self.rig.core.events() if re.search(pattern, text))

    def wait_moving(self, deadline_s: float = 10.0) -> None:
        _until(lambda: self.rig.read("TLM_MOVING") == [1], deadline_s, "TLM_MOVING == 1")

    def program_pubs(self) -> list[dict]:
        return [p for p in self.rec.at("program") if isinstance(p, dict)]

    def wait_program_final(self, state: str, since: int, deadline_s: float = 40.0) -> dict:
        """Дождаться публикации ``.program`` (после индекса ``since``) с итоговым ``state``."""

        def last() -> dict | None:
            items = self.program_pubs()[since:]
            return items[-1] if items else None

        _until(lambda: (last() or {}).get("state") == state, deadline_s, f".program.state == {state!r}")
        return last()  # type: ignore[return-value]


@contextmanager
def _hub(tmp_path: Path) -> Iterator[Hub]:
    """Менеджер хаба с драйвером v2 над ``E2eRig``; драйвер подключён, тик идёт раз в 0.1 с (как у супервизора)."""
    store = RobotDataStore(tmp_path / "robot")
    rec = Rec()
    mgr = DeviceManager(store=None, publish_cb=rec, spawn=_SCOPE.spawn, robot_store=store)
    with E2eRig() as rig:
        mgr.upsert(
            {
                "id": DEV,
                "name": DEV,
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            }
        )
        try:
            assert bounded(lambda: mgr.connect(DEV), _CONNECT_DEADLINE_S) is True, "connect() не вернул True"
            drv = mgr.get_driver(DEV)
            drv.desired_connected = True
            with pulse(lambda: drv.tick(None), 0.1):
                yield Hub(mgr, rig, rec, drv, store)
        finally:
            try:
                bounded(lambda: mgr.disconnect(DEV), _CALL_DEADLINE_S)
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


def _legs_program(name: str, legs: int) -> tuple[Program, dict[str, Point]]:
    """``legs`` ходов JOINT между двумя точками (дом -> a -> дом -> ...); одна нога ~0.27 с sim."""
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    steps = tuple(Move(point="a" if i % 2 == 0 else "b", kind="JOINT") for i in range(legs))
    return Program(name=name, steps=steps), points


def _timed(drv: Any, op: str, args: dict | None = None) -> tuple[dict, float]:
    """``drv.call(op, args)`` в daemon-потоке; (ответ, секунды). Не уложился в дедлайн — ответ-заглушка и дедлайн."""
    started = time.monotonic()
    try:
        answer = bounded(lambda: drv.call(op, dict(args or {})), _CALL_DEADLINE_S)
    except TimeoutError:
        return {"status": "error", "message": f"нет ответа за {_CALL_DEADLINE_S} с"}, time.monotonic() - started
    return answer, time.monotonic() - started


def _call_within(drv: Any, op: str, args: dict, deadline_s: float) -> dict:
    """Ответ ``drv.call`` или заглушка, если поток не вернулся за ``deadline_s`` (join(deadline_s) у daemon-потока)."""
    box: dict[str, Any] = {}

    def body() -> None:
        try:
            box["answer"] = drv.call(op, dict(args))
        except BaseException as exc:  # noqa: BLE001 — исключение вызова — тоже результат
            box["answer"] = {"status": "raised", "message": f"{type(exc).__name__}: {exc}"}

    thread = threading.Thread(target=body, name=f"t-call-{op}", daemon=True)
    thread.start()
    thread.join(deadline_s)
    return box.get("answer", {"status": "error", "message": f"нет ответа за {deadline_s} с"})


# --------------------------------------------------------------------------------------------------
# RED 9
# --------------------------------------------------------------------------------------------------


def test_resync_does_not_race_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пока идёт пересинхронизация по метке (первый ``PARAM_SET`` в шве), команды отказывают постоянным текстом."""
    with _hub(tmp_path) as hub:
        drv, rig = hub.drv, hub.rig
        two, points = _legs_program("two", 2)
        save_points(hub.store, DEV, points, base_rev=None)
        save_program(hub.store, DEV, two, base_rev=None)

        assert rig.read("TLM_CFG_EPOCH") == [DEFAULT_EPOCH]  # метка ПК стоит на роботе после подключения

        # (1) метки расходятся при ЖИВОМ соединении: рестарт sim, драйвер переподключается тиком до конца sync
        rig.restart(keep_regs=False)
        _until(
            lambda: rig.read("TLM_CFG_EPOCH") == [DEFAULT_EPOCH] and drv.is_connected and drv.transport.is_connected,
            _RECONNECT_DEADLINE_S,
            "драйвер переподключился и синхронизировал параметры (метка робота снова 1)",
        )

        # (2) шов на экземпляре клиента: первый PARAM_SET синхронизации стоит до исходного cmd (замок mailbox не держит)
        client = drv._client
        original_cmd = client.cmd
        guard = threading.Lock()
        seen = {"param_set": 0}
        entered = threading.Event()
        release = threading.Event()

        def seam(op: str, args: Any) -> Any:
            first = False
            if op == "PARAM_SET":
                with guard:
                    seen["param_set"] += 1
                    first = seen["param_set"] == 1
            if first:
                entered.set()
                release.wait(3.0)  # дедлайн шва: тест не повисает
            return original_cmd(op, args)

        monkeypatch.setattr(client, "cmd", seam)

        problems: list[str] = []
        try:
            # (3) подмена метки робота при живом соединении; тик (раз в 0.1 с) запустит пересинхронизацию
            rig.core.regs[REG["TLM_CFG_EPOCH"]] = 0
            # (4) ждать, пока поток синхронизации встанет в шве
            assert entered.wait(3.0), "пересинхронизация не дошла до первого PARAM_SET за 3 с (тест инвалиден)"

            # (5) в окне синхронизации: каждая команда — ровно постоянный текст отказа
            window_calls = (
                ("jog_hold", {"dir": 1, "spd": 20}),
                ("jog_step", {"dx": 1, "dy": 0, "spd": 20}),
                ("program_run", {"name": "two"}),
                ("param_set", {"name": "P_SPD_DEFAULT", "value": 55, "base_rev": None}),
                ("param_apply", {}),
            )
            for op, args in window_calls:
                answer = _call_within(drv, op, args, 2.0)
                if answer != SYNC_REPLY:
                    problems.append(f"{op} в окне синхронизации ответил {answer!r}, ждали {SYNC_REPLY!r}")
            moved = hub.count(r"op=(JOG_CONT|JOG_STEP)$")
            if moved:
                problems.append(f"в окне синхронизации до робота дошло {moved} команд движения (JOG_CONT/JOG_STEP)")
        finally:
            # (6) отпустить шов; на ошибке теста поток синхронизации не остаётся висеть
            release.set()

        # (6) синхронизация завершается: метка робота — метка ПК
        try:
            _until(lambda: rig.read("TLM_CFG_EPOCH") == [DEFAULT_EPOCH], 5.0, "метка робота вернулась к метке ПК")
        except AssertionError as exc:
            problems.append(str(exc))

        # (7) после окна команды работают; флаг синхронизации снят, сбоя синхронизации нет
        answer = _call_within(drv, "jog_hold", dict(_JOG), 2.0)
        end = time.monotonic() + 2.0
        while answer == SYNC_REPLY and time.monotonic() < end:  # флаг снимается чуть позже последней записи метки
            time.sleep(0.02)
            answer = _call_within(drv, "jog_hold", dict(_JOG), 2.0)
        if answer.get("status") != "ok":
            problems.append(f"jog_hold после окна ответил {answer!r}, ждали status ok")
        release_answer = _call_within(drv, "jog_release", {}, 5.0)
        if release_answer.get("status") != "ok":
            problems.append(f"jog_release после окна ответил {release_answer!r}, ждали status ok")

        end = time.monotonic() + 5.0  # отсутствие публикации — только ожиданием срока
        while time.monotonic() < end:
            time.sleep(0.1)
        failed = [p for p in hub.rec.at("last_error") if str(p).startswith(SYNC_FAILED_PREFIX)]
        if failed:
            problems.append(f"last_error о сбое синхронизации: {failed[0]!r}")

        assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------------------------------
# RED 11
# --------------------------------------------------------------------------------------------------


def test_handlers_return_within_one_second(tmp_path: Path) -> None:
    """Каждая из 15 операций при исправной связи возвращается не дольше 1,0 с и отвечает ``ok``."""
    with _hub(tmp_path) as hub:
        drv, rig = hub.drv, hub.rig
        long_program, points = _legs_program("long", 14)  # ~3.8 с хода
        save_points(hub.store, DEV, points, base_rev=None)
        save_program(hub.store, DEV, long_program, base_rev=None)
        _, points_rev = load_points(hub.store, DEV)

        rows: list[tuple[str, dict, float]] = []  # (метка, ответ, секунды)

        def measure(op: str, args: dict | None = None, *, label: str | None = None) -> dict:
            answer, elapsed = _timed(drv, op, args)
            rows.append((label or op, answer, elapsed))
            return answer

        def run_long(label: str) -> tuple[bool, int]:
            """Измеренный ``program_run``; занятость от прошлого прогона (``_busy`` снимается после итога) — повтор."""
            since = len(hub.program_pubs())
            end = time.monotonic() + 5.0
            while True:
                answer = measure("program_run", {"name": "long"}, label=label)
                if answer != BUSY_PROGRAM or time.monotonic() >= end:
                    break
                rows.pop()
                time.sleep(0.05)
            started = answer.get("status") == "ok"
            if started:
                try:
                    hub.wait_moving(3.0)  # блокирующий program_run (d-I14) вернулся бы уже после конца хода
                except AssertionError:
                    started = False
            return started, since

        def finish(since: int) -> None:
            hub.wait_program_final("aborted", since)

        def during_slow_step(dx: int, op: str, args: dict, label: str) -> None:
            """``op`` во время медленного ``jog_step`` (spd 1: ~3,3 с хода). SOFT посреди одиночного хода sim
            откладывает до цели — эхо не приходит, ждать его дольше предела нельзя. В прогоне программы так не
            выходит: ``run_chunks`` сам дописывает HARD, и эхо приходит сразу."""
            answer, _ = _timed(drv, "jog_step", {"dx": dx, "dy": 0, "spd": 1})
            if answer.get("status") != "ok":
                return  # отказ jog_step виден по строке ``jog_step`` выше
            hub.wait_moving()
            measure(op, args, label=label)
            _until(lambda: rig.read("TLM_MOVING") == [0], 10, "TLM_MOVING == 0: отложенный SOFT снят у цели")

        # --- простой робот ---
        measure("get_telemetry")
        measure("servo", {"on": True})
        measure("do_set", {"ch": 3, "on": True})
        if measure("jog_step", {"dx": 10, "dy": 0, "spd": 50}).get("status") == "ok":
            _until(lambda: rig.read("TLM_MOVING") == [0], 10, "TLM_MOVING == 0 после jog_step")
        measure("point_capture", {"name": "cap", "base_rev": points_rev})
        measure("param_set", {"name": "P_SPD_DEFAULT", "value": 55, "base_rev": None})
        measure("param_apply")

        # --- во время одиночного медленного хода: SOFT откладывается до цели, эхо не приходит ---
        during_slow_step(50, "stop", {"level": "SOFT"}, "stop#2")
        during_slow_step(-50, "abort", {"mode": 1}, "abort#2")

        # jog_hold и сразу jog_release: окно удержания 0,2 с, jog активен, release пишет стоп и ждёт эхо
        measure("jog_hold", dict(_JOG))
        measure("jog_release")

        # --- во время хода программы: stop, abort, program_abort (по одному на прогон) ---
        started, since = run_long("program_run")
        if started:
            measure("stop", {"level": "SOFT"})  # SOFT посреди хода откладывается до цели: эхо может не прийти
            finish(since)
        started, since = run_long("program_run#2")
        if started:
            measure("abort", {"mode": 1})
            finish(since)
        started, since = run_long("program_run#3")
        if started:
            measure("program_abort")
            finish(since)

        # --- задания: ответ после постановки в очередь ---
        measure("enqueue_job", {"x_mm": 300, "y_mm": -150})
        measure("return_job", {"x_mm": 300, "y_mm": -150})
        end = time.monotonic() + 25.0  # тик исполняет очереди; уборка не падает по результату заданий
        while time.monotonic() < end:
            if drv.jobs_done + drv.jobs_failed >= 1 and drv.returns_done + drv.returns_failed >= 1:
                break
            time.sleep(0.1)

        listing = "\n".join(f"  {label}: {elapsed:.3f} c {answer!r}" for label, answer, elapsed in rows)
        failed = [f"{label}: {answer!r}" for label, answer, _ in rows if answer.get("status") != "ok"]
        assert not failed, "операции ответили не ok:\n" + "\n".join(failed) + f"\nвсе замеры:\n{listing}"
        slow = [f"{label}: {elapsed:.3f} c" for label, _, elapsed in rows if elapsed > HANDLER_LIMIT_S]
        assert not slow, f"дольше {HANDLER_LIMIT_S} с:\n" + "\n".join(slow) + f"\nвсе замеры:\n{listing}"
        measured = {re.sub(r"#\d+$", "", label) for label, _, _ in rows}
        assert measured == OPS_15, f"замерены не все 15 операций: нет {sorted(OPS_15 - measured)}\n{listing}"


# --------------------------------------------------------------------------------------------------
# RED 12
# --------------------------------------------------------------------------------------------------


class _Executor:
    """Один поток-исполнитель с очередью (как ``message_processor``, Ф8): команды идут строго по одной."""

    def __init__(self, drv: Any) -> None:
        self._drv = drv
        self._queue: queue.Queue[tuple[str, dict, dict] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._body, name="t-executor", daemon=True)
        self._thread.start()

    def _body(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            op, args, box = item
            try:
                box["answer"] = self._drv.call(op, dict(args))
            except BaseException as exc:  # noqa: BLE001
                box["answer"] = {"status": "raised", "message": f"{type(exc).__name__}: {exc}"}
            box["t_done"] = time.monotonic()
            box["done"].set()

    def submit(self, op: str, args: dict) -> dict:
        box: dict[str, Any] = {"done": threading.Event(), "t_submit": time.monotonic()}
        self._queue.put((op, args, box))
        return box

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(10.0)


def test_stop_during_jog_release_answers_within_1_5s(tmp_path: Path) -> None:
    """Очередь одного исполнителя: ``jog_release`` (jog активен), затем ``stop``; ответ ``stop`` ≤ 1,5 с."""
    with _hub(tmp_path) as hub:
        drv = hub.drv
        executor = _Executor(drv)
        try:
            answer, _ = _timed(drv, "jog_hold", dict(_JOG))
            assert answer["status"] == "ok", answer  # jog активен до постановки в очередь

            release_box = executor.submit("jog_release", {})
            stop_box = executor.submit("stop", {"level": "SOFT"})  # t_submit — постановка в очередь

            assert stop_box["done"].wait(10.0), "stop не ответил за 10 с"
            elapsed = stop_box["t_done"] - stop_box["t_submit"]
            assert release_box["done"].wait(1.0), "jog_release не ответил"
            assert release_box["answer"] == {"status": "ok"}, release_box["answer"]
            assert stop_box["answer"] == {"status": "ok", "level": "SOFT", "echo": True}, stop_box["answer"]
            assert elapsed <= STOP_AFTER_RELEASE_LIMIT_S, (
                f"stop ответил через {elapsed:.3f} с от постановки, предел {STOP_AFTER_RELEASE_LIMIT_S} с"
            )
        finally:
            executor.close()


# --------------------------------------------------------------------------------------------------
# RED 15
# --------------------------------------------------------------------------------------------------


def test_stop_not_blocked_by_inflight_jog_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``jog_release`` застрял на ожидании эха (шов 2,0 с, только в его потоке): ``stop`` отвечает ≤ 1,5 с."""
    with _hub(tmp_path) as hub:
        drv = hub.drv
        client = drv._client
        original_await = client.await_stop_echo
        state: dict[str, Any] = {"release_ident": None}
        in_seam = threading.Event()

        def seam(value: int, level: int, *, deadline: float) -> Any:
            if threading.get_ident() == state["release_ident"]:
                in_seam.set()
                time.sleep(SEAM_SLEEP_S)  # сон только в потоке jog_release, ДО исходного метода, вне замков клиента
            return original_await(value, level, deadline=deadline)

        monkeypatch.setattr(client, "await_stop_echo", seam)

        release_result: dict[str, Any] = {}
        stop_result: dict[str, Any] = {}

        def release_body() -> None:
            state["release_ident"] = threading.get_ident()  # поток 1 помечает себя при старте
            started = time.monotonic()
            release_result["answer"] = drv.call("jog_release", {})
            release_result["elapsed"] = time.monotonic() - started

        def stop_body() -> None:
            started = time.monotonic()
            stop_result["answer"] = drv.call("stop", {"level": "SOFT"})
            stop_result["elapsed"] = time.monotonic() - started

        release_thread = threading.Thread(target=release_body, name="t-release", daemon=True)
        stop_thread = threading.Thread(target=stop_body, name="t-stop", daemon=True)
        try:
            answer, _ = _timed(drv, "jog_hold", dict(_JOG))
            assert answer["status"] == "ok", answer  # jog активен: jog_release будет писать стоп и ждать эхо

            release_thread.start()
            assert in_seam.wait(2.0), "jog_release не дошёл до ожидания эха за 2 с (jog не был активен, тест инвалиден)"
            stop_thread.start()  # jog_release держит свой путь стопа и спит в шве
            stop_thread.join(10.0)
            assert not stop_thread.is_alive(), "stop не вернулся за 10 с"
            assert stop_result["answer"]["status"] == "ok", stop_result["answer"]
            assert stop_result["answer"]["level"] == "SOFT", stop_result["answer"]
            assert stop_result["elapsed"] <= STOP_AFTER_RELEASE_LIMIT_S, (
                f"stop ответил через {stop_result['elapsed']:.3f} с при jog_release в полёте, "
                f"предел {STOP_AFTER_RELEASE_LIMIT_S} с"
            )
        finally:
            release_thread.join(10.0)
            assert not release_thread.is_alive(), "jog_release не вернулся за 10 с после шва"
        assert release_result["elapsed"] >= SEAM_SLEEP_S - 0.1, (
            f"шов не задержал jog_release: {release_result['elapsed']:.3f} с (тест инвалиден)"
        )
