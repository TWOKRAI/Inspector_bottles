"""Слепая приёмка T5.3d часть d1: операции ``RobotDriverV2`` против sim v2 (plans/robot-protocol-v2/tasks/T5.3d.md).

Purpose:
    Десять приёмочных тестов REDS 1–8, 13, 14: ``stop``, ``servo``, ``do_set``, ``jog_step``, ``point_capture``,
    ``param_set``, ``param_apply``, ``program_run``, ``program_abort`` и проверка аргументов ``jog_hold``. Стенд —
    ``DeviceManager(store=None, publish_cb=rec, spawn=scope.spawn, robot_store=RobotDataStore(tmp_path / "robot"))``
    над ``E2eRig`` (sim v2); операции идут через ``DeviceManager.call``. Проверяется наблюдаемый эффект: ответ,
    регистры sim (``rig.read``), строки событий sim (``op=...``), ``points.yaml`` / ``params.yaml`` на диске,
    публикации ``.program`` / ``.params``. Спаев на имена методов нет.

Public API:
    Только тесты ``test_*``. Имена, которых ещё нет в базе (``robot_store`` у ``DeviceManager``), используются
    только в телах тестов: сборка проходит, каждый тест краснеет сам.

Stability: lite

Допущения теста (не из спеки, прочитаны у sim):
    * Запись NAK в событиях sim следа не оставляет (строка ``op=`` пишется только на ACK): «ни одной новой
      ``op=PARAM_SET``» ловит ЛИШНЮЮ УСПЕШНУЮ запись; отказ с текстом ловит ответ.
    * ``run_chunks`` сам пишет HARD, когда видит стоп оператора: счёт ``STOP_REQ`` по значению после конца
      программы невозможен — записи стопа считаются по журналу обмена драйвера (``_StopWatcher``), по уровню.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.manager import DeviceManager
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.robot_data import save_points, save_program
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

# --------------------------------------------------------------------------------------------------
# Литералы брифа
# --------------------------------------------------------------------------------------------------

DEV = "rob_v2"
HOME_POSE = (300.0, -210.0, -40.0, -100.0)  # поза sim после подъёма (дом P_HOME_*)
TEXT_BAD_ARGS = "неверные аргументы команды робота"  # TEXT_BAD_ARGS из robot_data_ops.py (T5.3c, не на базе)
TEXT_BAD_LEVEL = "неверный уровень стопа"
TEXT_NO_STORE = "хранилище данных робота не задано"
TEXT_BAD_RANGE = "значение вне диапазона"
TEXT_STALE = "Данные робота изменены с момента чтения"
TEXT_NO_PROGRAM = "программа не найдена"
TEXT_BAD_DO = "канал DO вне 1..16"
TEXT_E_BUSY = "Робот занят другой командой"  # delta_v2.yaml, ERR E_BUSY
BUSY_PROGRAM = {"status": "error", "message": "робот занят программой"}

_CALL_DEADLINE_S = 15.0
_CONNECT_DEADLINE_S = 60.0  # connect включает sync_params (десятки PARAM_SET)
_SCOPE_BUDGET_S = 6.0
_STOP_SEQ_MOD = 0x3FFF
_LOG_LIMIT = 2000  # limit exchange_log_get = размер кольца журнала


# --------------------------------------------------------------------------------------------------
# Область потоков теста (драйвер без spawn потоков не запускает)
# --------------------------------------------------------------------------------------------------

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2ops", budget_s=_SCOPE_BUDGET_S)
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


class _StopWatcher:
    """Записи ``STOP_REQ`` за время блока — по журналу обмена драйвера, в точке записи (без опроса регистра).

    Журнал (T5.6) стоит между драйвером и транспортом: в нём каждая запись ``STOP_REQ`` драйвера и клиента
    (в том числе HARD, который ``run_chunks`` дописывает сам) — строка ``W STOP_REQ = <значение>``, повтор
    одного значения склеен полем ``n``. Опрос регистра раз в 1 мс промахивался мимо SOFT, когда HARD ложился
    через < 1 мс (ревью, 2 промаха из 12).
    """

    _LINE = re.compile(r"^W STOP_REQ = (\d+)$")

    def __init__(self, drv: Any) -> None:
        self._drv = drv
        self._since = 0
        self.values: list[int] = []

    def _get(self, since_seq: int, *, complete: bool) -> dict:
        answer = bounded(
            lambda: self._drv.call("exchange_log_get", {"since_seq": since_seq, "limit": _LOG_LIMIT}), _CALL_DEADLINE_S
        )
        assert answer["status"] == "ok", answer
        # Ответ полный: строк меньше limit — limit ничего не отрезал (иначе «HALT не писался» прошёл бы зря).
        if complete:  # только чтение конца блока: у входа кольцо может быть заполнено целиком (2000), это не усечение
            assert len(answer["lines"]) < _LOG_LIMIT, len(answer["lines"])
        return answer

    def __enter__(self) -> _StopWatcher:
        self._since = self._get(0, complete=False)["last_seq"] + 1  # строки блока: seq выше последнего до входа
        return self

    def __exit__(self, *_exc: object) -> None:
        state = self._get(self._since, complete=True)
        assert state["dropped"] == 0, state["dropped"]  # кольцо журнала не потеряло строк блока
        for line in state["lines"]:
            match = self._LINE.match(line["text"])
            if match:
                self.values.extend([int(match.group(1))] * line["n"])

    def levels(self) -> list[int]:
        """Уровни (``& 3``) записей ``STOP_REQ`` блока, по порядку."""
        return [value & 3 for value in self.values]


@dataclass
class Hub:
    mgr: DeviceManager
    rig: E2eRig
    rec: Rec
    drv: Any
    store: RobotDataStore | None
    root: Path  # каталог документов устройства: <tmp>/robot/<DEV>

    def call(self, op: str, args: dict | None = None) -> dict:
        return bounded(lambda: self.mgr.call(DEV, op, dict(args or {})), _CALL_DEADLINE_S)

    def start_program(self, program: Program, points: dict[str, Point]) -> dict:
        return bounded(lambda: self.drv.start_program(program, points, None, name=program.name), _CALL_DEADLINE_S)

    def count(self, pattern: str) -> int:
        """Сколько строк событий sim (на ACK) подходит под ``pattern``."""
        return sum(1 for _, text in self.rig.core.events() if re.search(pattern, text))

    def param_sets(self) -> int:
        return self.count(r"op=PARAM_SET$")

    def wait_moving(self, deadline_s: float = 10.0) -> None:
        _until(lambda: self.rig.read("TLM_MOVING") == [1], deadline_s, "TLM_MOVING == 1")

    def wait_program(self, state: str, deadline_s: float = 40.0, *, since: int = 0) -> dict:
        def last() -> dict | None:
            items = [p for p in self.rec.at("program")[since:] if isinstance(p, dict)]
            return items[-1] if items else None

        _until(lambda: (last() or {}).get("state") == state, deadline_s, f".program.state == {state!r}")
        return last()  # type: ignore[return-value]


@contextmanager
def _hub(tmp_path: Path, *, with_store: bool = True) -> Iterator[Hub]:
    """Менеджер хаба с драйвером v2 над ``E2eRig``; драйвер подключён, тик идёт раз в 0.1 с (как у супервизора)."""
    store = RobotDataStore(tmp_path / "robot") if with_store else None
    kwargs: dict[str, Any] = {"robot_store": store} if with_store else {}
    rec = Rec()
    mgr = DeviceManager(store=None, publish_cb=rec, spawn=_SCOPE.spawn, **kwargs)
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
                yield Hub(mgr, rig, rec, drv, store, tmp_path / "robot" / DEV)
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


def _s16(word: int) -> int:
    return word - 0x10000 if word >= 0x8000 else word


def _pose(rig: E2eRig) -> tuple[float, float, float, float]:
    return rig.pose_wire()


def _jog_to_x310(hub: Hub) -> None:
    """``jog_step`` на +10 мм по X от дома; ждёт конца хода. Поза после: (310.0, -210.0, -40.0, -100.0)."""
    answer = hub.call("jog_step", {"dx": 10, "dy": 0, "spd": 50})
    assert answer["status"] == "ok", answer
    _until(lambda: abs(_pose(hub.rig)[0] - 310.0) <= 0.05 and hub.rig.read("TLM_MOVING") == [0], 10, "x_mm == 310.0")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------------------------------
# REDS 1
# --------------------------------------------------------------------------------------------------


def test_stop_levels(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        program, points = _legs_program("long", 10)  # ~2.7 с
        assert hub.start_program(program, points)["status"] == "ok"
        hub.wait_moving()
        with _StopWatcher(hub.drv) as watcher:
            answer = hub.call("stop", {"level": "SOFT"})  # стоп оператора не проверяет занятость (программа идёт)
            final = hub.wait_program("aborted")
        assert answer["status"] == "ok", answer
        assert answer["level"] == "SOFT"
        assert isinstance(answer["echo"], bool)  # SOFT посреди хода в sim откладывается: echo False законен
        assert final["state"] == "aborted"
        assert 1 in watcher.levels()  # запись SOFT дошла до робота
        assert 3 not in watcher.levels()  # HALT не писался

        time.sleep(0.3)  # _busy снимается сразу после итога .program
        before = hub.rig.read("STOP_REQ")
        for bad in ("BOGUS", True, 7, 0):  # bool — не уровень (как у abort)
            assert hub.call("stop", {"level": bad}) == {"status": "error", "message": TEXT_BAD_LEVEL}
        assert hub.rig.read("STOP_REQ") == before  # плохой уровень робота не трогает

        # формы уровня: ключ любого регистра и int 1..3; простой робот эхо отдаёт сразу
        assert hub.call("stop", {"level": "soft"}) == {"status": "ok", "level": "SOFT", "echo": True}
        assert hub.call("stop", {"level": 2}) == {"status": "ok", "level": "HARD", "echo": True}


# --------------------------------------------------------------------------------------------------
# REDS 2
# --------------------------------------------------------------------------------------------------


def test_servo_and_do(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        rig = hub.rig
        assert rig.read("TLM_SERVO") == [1]  # стенд поднят с серво

        assert hub.call("servo", {"on": False})["status"] == "ok"
        _until(lambda: rig.read("TLM_SERVO") == [0], 2, "TLM_SERVO == 0")
        assert hub.call("servo", {"on": True})["status"] == "ok"
        _until(lambda: rig.read("TLM_SERVO") == [1], 2, "TLM_SERVO == 1")

        assert hub.call("do_set", {"ch": 3, "on": True})["status"] == "ok"
        assert rig.read("TLM_DO_MASK")[0] == 0b100  # DO3 = бит 2
        assert hub.call("do_set", {"ch": 3, "on": False})["status"] == "ok"
        assert rig.read("TLM_DO_MASK")[0] == 0
        assert hub.call("do_set", {"ch": 16, "on": True})["status"] == "ok"  # верхняя граница
        assert rig.read("TLM_DO_MASK")[0] == 1 << 15

        for ch in (17, 0):  # обе стороны границы 1..16
            assert hub.call("do_set", {"ch": ch, "on": True}) == {"status": "error", "message": TEXT_BAD_DO}
        assert rig.read("TLM_DO_MASK")[0] == 1 << 15  # отказ маску не трогает


# --------------------------------------------------------------------------------------------------
# REDS 3
# --------------------------------------------------------------------------------------------------


def test_jog_step_moves_pose(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        assert _pose(hub.rig) == HOME_POSE
        answer = hub.call("jog_step", {"dx": 10, "dy": 0, "spd": 50})
        assert answer["status"] == "ok", answer
        assert isinstance(answer["seq"], int)  # ответ после ACK, без ожидания DONE
        _until(lambda: abs(_pose(hub.rig)[0] - 310.0) <= 0.05, 10, "x_mm == 310.0")
        _until(lambda: hub.rig.read("TLM_MOVING") == [0], 10, "TLM_MOVING == 0")
        x, y, z, rz = _pose(hub.rig)
        assert x == pytest.approx(310.0, abs=0.05)
        assert (y, z, rz) == HOME_POSE[1:]  # прочие оси прежние

        program, points = _legs_program("long", 8)
        assert hub.start_program(program, points)["status"] == "ok"
        hub.wait_moving()
        assert hub.call("jog_step", {"dx": 10, "dy": 0, "spd": 50}) == BUSY_PROGRAM
        hub.wait_program("done")


# --------------------------------------------------------------------------------------------------
# REDS 4
# --------------------------------------------------------------------------------------------------


def test_point_capture_saves_pose(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        _jog_to_x310(hub)
        answer = hub.call("point_capture", {"name": "p", "base_rev": None})
        assert answer["status"] == "ok", answer
        point = answer["point"]
        assert point["name"] == "p"
        assert point["x"] == pytest.approx(310.0, abs=0.05)
        assert (point["y"], point["z"], point["rz"]) == pytest.approx(HOME_POSE[1:], abs=0.05)
        assert point["hand"] == hub.rig.read("TLM_HAND")[0]
        points_file = hub.root / "points.yaml"
        body = yaml.safe_load(points_file.read_text(encoding="utf-8"))  # ответ — после записи файла (О9-а)
        assert [p["name"] for p in body["points"]] == ["p"]
        assert body["points"][0]["x"] == pytest.approx(310.0, abs=0.05)
        rev1 = answer["rev"]
        assert rev1 == _sha(points_file)

        second = hub.call("point_capture", {"name": "q", "base_rev": rev1})
        assert second["status"] == "ok", second
        names = [p["name"] for p in yaml.safe_load(points_file.read_text(encoding="utf-8"))["points"]]
        assert sorted(names) == ["p", "q"]
        rev2 = second["rev"]
        assert rev2 == _sha(points_file)
        assert rev2 != rev1

        stale = hub.call("point_capture", {"name": "r", "base_rev": rev1})  # rev1 уже устарел
        assert stale["status"] == "error"
        assert stale["message"] == TEXT_STALE
        assert _sha(points_file) == rev2  # файл цел


# --------------------------------------------------------------------------------------------------
# REDS 5
# --------------------------------------------------------------------------------------------------


def test_param_set_ack_saves_and_bumps_epoch(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        before = hub.param_sets()
        answer = hub.call("param_set", {"name": "P_SPD_DEFAULT", "value": 55, "base_rev": None})
        after_answer = hub.param_sets()
        assert answer["status"] == "ok", answer
        assert answer["name"] == "P_SPD_DEFAULT"
        assert answer["raw"] == 55
        assert answer["value"] == 55
        assert answer["epoch"] == 2
        assert isinstance(answer["rev"], str)

        assert bounded(lambda: hub.rig.client.param_get("P_SPD_DEFAULT")) == 55  # робот держит новое значение
        assert hub.rig.read("TLM_CFG_EPOCH") == [2]  # метка ПК поднята
        params_file = hub.root / "params.yaml"
        body = yaml.safe_load(params_file.read_text(encoding="utf-8"))
        assert body["epoch"] == 2
        assert body["values"]["P_SPD_DEFAULT"] == 55
        assert answer["rev"] == _sha(params_file)
        published = hub.rec.at("params")[-1]  # devices.state.<id>.params
        assert published["epoch"] == 2
        assert published["rev"] == answer["rev"]
        assert published["values"]["P_SPD_DEFAULT"] == {"raw": 55, "value": 55}

        assert after_answer - before == 2  # значение и метка, больше ничего
        time.sleep(3.0)  # тик не видит расхождения меток -> полной пересинхронизации нет
        assert hub.param_sets() == after_answer


# --------------------------------------------------------------------------------------------------
# REDS 6
# --------------------------------------------------------------------------------------------------


def test_param_set_refusals_leave_robot_and_file(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        # Файл создаётся удачной записью; дальше все отказы идут с её ревизией и байты не должны меняться.
        first = hub.call("param_set", {"name": "P_SPD_DEFAULT", "value": 55, "base_rev": None})
        assert first["status"] == "ok", first
        params_file = hub.root / "params.yaml"
        file_bytes = params_file.read_bytes()
        rev = first["rev"]
        writes = hub.param_sets()

        for name, value in (("P_SPD_DEFAULT", 500), ("P_WDG_TIMEOUT_MS", 0)):  # вне таблицы; «сторож 0» не принимается
            refused = hub.call("param_set", {"name": name, "value": value, "base_rev": rev})
            assert refused == {"status": "error", "message": TEXT_BAD_RANGE}, (name, refused)
            assert hub.param_sets() == writes  # робот не тронут
            assert params_file.read_bytes() == file_bytes

        # idle-параметр во время программы: робот отвечает NAK E_BUSY, файл не меняется
        program, points = _legs_program("long", 8)
        assert hub.start_program(program, points)["status"] == "ok"
        hub.wait_moving()
        busy = hub.call("param_set", {"name": "P_SPD_L", "value": 1000, "base_rev": rev})
        assert busy["status"] == "error"
        assert busy["message"] == TEXT_E_BUSY
        assert params_file.read_bytes() == file_bytes
        assert hub.param_sets() == writes
        hub.wait_program("done")


# --------------------------------------------------------------------------------------------------
# REDS 7
# --------------------------------------------------------------------------------------------------


def test_param_apply_clears_pending(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        assert hub.rig.read("TLM_CFG_PENDING") == [0]  # после подключения применено всё
        # P_VFD_SLAVE — apply: reinit (delta_v2.yaml:653), min 1 max 247, scale 1
        answer = hub.call("param_set", {"name": "P_VFD_SLAVE", "value": 2, "base_rev": None})
        assert answer["status"] == "ok", answer
        assert hub.rig.read("TLM_CFG_PENDING") == [1]
        assert hub.call("param_apply", {})["status"] == "ok"
        _until(lambda: hub.rig.read("TLM_CFG_PENDING") == [0], 2, "TLM_CFG_PENDING == 0")


# --------------------------------------------------------------------------------------------------
# REDS 8
# --------------------------------------------------------------------------------------------------


def test_program_run_progress_and_abort(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        store = hub.store
        two, points = _legs_program("two", 2)
        long, _ = _legs_program("long", 10)
        save_points(store, DEV, points, base_rev=None)
        save_program(store, DEV, two, base_rev=None)
        save_program(store, DEV, long, base_rev=None)

        assert hub.call("program_run", {"name": "nope"}) == {"status": "error", "message": TEXT_NO_PROGRAM}

        since = len(hub.rec.at("program"))
        started = hub.call("program_run", {"name": "two"})
        assert started["status"] == "ok", started
        hub.wait_program("done", 30, since=since)
        pubs = [p for p in hub.rec.at("program")[since:] if isinstance(p, dict)]
        assert pubs[0]["state"] == "running"
        dones = [p["done"] for p in pubs]
        assert dones == sorted(dones)  # done не убывает
        assert pubs[-1]["state"] == "done"
        assert pubs[-1]["total"] == 2
        assert pubs[-1]["done"] == pubs[-1]["total"]

        time.sleep(0.3)  # _busy снимается сразу после итога .program
        since = len(hub.rec.at("program"))
        assert hub.call("program_run", {"name": "long"})["status"] == "ok"
        hub.wait_moving()
        assert hub.call("program_run", {"name": "two"}) == BUSY_PROGRAM  # второй запуск во время первого

        with _StopWatcher(hub.drv) as watcher:
            answer = hub.call("program_abort", {})  # только запись SOFT, без эха
            final = hub.wait_program("aborted", 40, since=since)
        assert answer == {"status": "ok", "stopped": True}
        assert watcher.levels().count(1) == 1  # ОДНА запись SOFT (HARD дописывает run_chunks сам)
        assert 3 not in watcher.levels()
        assert final["state"] == "aborted"

        time.sleep(0.3)
        req, ack = hub.rig.read("STOP_REQ"), hub.rig.read("TLM_STOP_ACK")
        assert hub.call("program_abort", {}) == {"status": "ok", "stopped": False}  # программы нет — записи нет
        assert hub.rig.read("STOP_REQ") == req
        assert hub.rig.read("TLM_STOP_ACK") == ack


# --------------------------------------------------------------------------------------------------
# REDS 13
# --------------------------------------------------------------------------------------------------


def test_store_none_refuses(tmp_path: Path) -> None:
    with _hub(tmp_path, with_store=False) as hub:
        writes = hub.param_sets()
        epoch = hub.rig.read("TLM_CFG_EPOCH")
        for op, args in (
            ("point_capture", {"name": "p", "base_rev": None}),
            ("program_run", {"name": "x"}),
            ("param_set", {"name": "P_SPD_DEFAULT", "value": 55, "base_rev": None}),
        ):
            assert hub.call(op, args) == {"status": "error", "message": TEXT_NO_STORE}, op
        assert hub.param_sets() == writes  # робот не тронут
        assert hub.rig.read("TLM_CFG_EPOCH") == epoch  # метка прежняя


# --------------------------------------------------------------------------------------------------
# REDS 14
# --------------------------------------------------------------------------------------------------

_WRITE_OPS = r"op=(JOG_STEP|JOG_CONT|SERVO|DO_SET|PARAM_SET|PARAM_APPLY)$"


def test_bad_args_leave_robot_untouched(tmp_path: Path) -> None:
    with _hub(tmp_path) as hub:
        rig = hub.rig
        writes = hub.count(_WRITE_OPS)
        stop_req = rig.read("STOP_REQ")

        # операции без jog_hold: постоянный текст, входное значение в нём не появляется
        answer = hub.call("jog_step", {"dx": "abc", "dy": 0, "spd": 50})
        assert answer == {"status": "error", "message": TEXT_BAD_ARGS}
        assert "abc" not in answer["message"]
        for op, args in (
            ("jog_step", {"dx": 1, "dy": 0, "spd": 500}),  # ключ dy есть — отказ именно из-за spd
            ("servo", {"on": "yes"}),
            ("do_set", {"ch": "x", "on": True}),
            ("param_set", {"name": "P_SPD_DEFAULT", "value": True, "base_rev": None}),  # bool — не число
        ):
            assert hub.call(op, args) == {"status": "error", "message": TEXT_BAD_ARGS}, (op, args)

        # jog_hold: плохие dir / spd — отказ до робота
        bad_hold = (
            {"dir": "abc", "spd": 50},
            {"dir": 9, "spd": 50},
            {"dir": 0, "spd": 50},
            {"dir": True, "spd": 50},
            {"spd": 50},  # нет dir
            {"dir": 1, "spd": 0},
            {"dir": 1, "spd": 101},
        )
        for args in bad_hold:
            answer = hub.call("jog_hold", args)
            assert answer == {"status": "error", "message": TEXT_BAD_ARGS}, args
            assert "abc" not in answer["message"]

        assert hub.count(_WRITE_OPS) == writes  # ни JOG_CONT, ни прочих записей
        assert hub.count(r"op=JOG_CONT$") == 0
        assert _pose(rig) == HOME_POSE  # поза прежняя
        assert rig.read("TLM_SERVO") == [1]
        assert rig.read("TLM_DO_MASK") == [0]
        assert hub.call("jog_release", {}) == {"status": "ok"}  # поток поводка не запущен: стопа нет
        assert rig.read("STOP_REQ") == stop_req

        # контроль: верные аргументы проходят
        assert hub.call("jog_hold", {"dir": 1, "spd": 20})["status"] == "ok"
        assert hub.call("jog_release", {})["status"] == "ok"
