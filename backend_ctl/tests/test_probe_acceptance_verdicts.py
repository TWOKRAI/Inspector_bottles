# -*- coding: utf-8 -*-
"""Task 0.13 — вердикты зонда `probe_observability_consumer_acceptance` без стенда.

Что может сломаться в ЭТОМ механизме:
* O-1: имена процессов затёрты именами команд → S2 (`cap_names == names`) всегда ложь, S5 перебирает
  команды вместо процессов — ложный FAIL приёмки;
* вердикт SF1 принимает `fresh` или `no_data` за «устарело» → остановленный писатель «проходит»;
* предусловие не ловит ложную тревогу у ЖИВОГО писателя (возраст метки ≥ 2 тактов);
* SIGSTOP уходит в ProcessManager (стенд замирает целиком);
* SIGCONT не в `finally` → исключение читателя оставляет писателя остановленным навсегда;
* рестарт супервизором во время стопа засчитан как PASS/FAIL, хотя читатели видят новое воплощение.

Драйвер подставной: интерфейс — ровно то, что зовёт зонд. Всё, что может зависнуть, идёт в daemon-потоке
с join-дедлайном. Ожидаемые значения — литералы, не выводятся из кода под тестом.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import signal
import threading
from types import SimpleNamespace
from typing import Any, Callable

import pytest

MODULE = "backend_ctl.probes.probe_observability_consumer_acceptance"

PROCS = ["ProcessManager", "camera_0", "gui", "inspector", "processor", "renderer", "storage"]
#: Метку `_fresh` публикуют дети; ProcessManager и gui — нет (стенд фазы 0).
NO_LABEL = {"ProcessManager", "gui"}
NEED_CMDS = [
    "config.reload",
    "introspect.observability",
    "observability.sink.enable",
    "observability.sink.disable",
    "health.report",
    "diag.thread_raise",
    "diag.warn",
    "introspect.telemetry",
]
DEADLINE_S = 20.0


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    """Импорт зонда с изолированным каталогом логов; env процесса pytest восстанавливается."""
    saved = dict(os.environ)
    os.environ["MULTIPROCESS_LOG_DIR"] = str(tmp_path_factory.mktemp("probe_logs"))
    try:
        mod = importlib.import_module(MODULE)
        yield mod
    finally:
        os.environ.clear()
        os.environ.update(saved)


def run_bounded(fn: Callable[[], Any], deadline: float = DEADLINE_S) -> Any:
    """Вызов в daemon-потоке с join-дедлайном: зависание = падение теста, а не прогона."""
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в потоке теста
            box["exc"] = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def rows_by_id(probe) -> dict[str, dict]:
    return {r["id"]: r for r in probe.ROWS}


# ---------------------------------------------------------------------------
# O-1: S2 и S5 на самоописании семи процессов (camera_0 — 68 команд)
# ---------------------------------------------------------------------------


class SelfDescDriver:
    """Подставной драйвер для `family_self_description`: 7 процессов, у camera_0 68 команд."""

    def system_overview(self, timeout=None):
        return {"processes": {p: {} for p in PROCS}, "anomalies": []}

    def capabilities(self, timeout=None):
        extra = [f"misc.cmd_{i}" for i in range(60)]  # 8 + 60 = 68 (число стенда ревизии)
        cards = {p: SimpleNamespace(commands={"introspect.status": {}}) for p in PROCS}
        cards["camera_0"] = SimpleNamespace(commands={c: {} for c in NEED_CMDS + extra})
        return SimpleNamespace(processes=cards)

    def send_command(self, process, command, data=None, timeout=None):
        return {"success": True, "result": {}}

    def introspect_telemetry(self, process, timeout=None):
        return {"success": True, "gate_active": True, "resolved": {"fps": {}}, "levels": {}, "tick_effective_sec": 5.0}

    def supervision_status(self, process=None, timeout=None):
        return {
            "success": True,
            "result": {"processes": {p: {"pid": 500 + i, "instance_restarts": 0} for i, p in enumerate(PROCS)}},
        }


@pytest.fixture
def self_desc_rows(probe, monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "ROWS", [])
    for p in PROCS:
        (tmp_path / p).mkdir()
        (tmp_path / p / "system.log").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(probe, "LOG_DIR", tmp_path)
    run_bounded(lambda: probe.family_self_description(SelfDescDriver()))
    return rows_by_id(probe)


def test_s2_pass_when_all_commands_present(self_desc_rows):
    s2 = self_desc_rows["S2"]
    assert "отсутствуют: нет" in s2["observed"]
    assert s2["verdict"] == "PASS"


def test_s5_iterates_processes(self_desc_rows):
    s5 = self_desc_rows["S5"]
    assert "каталогов с журналами: 7/7" in s5["observed"]
    assert s5["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# SF1: чистые функции
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answers", "verdict"),
    [
        pytest.param({"tree": "stale", "read_model": "stale", "snapshot": "stale"}, "PASS", id="three_stale"),
        pytest.param({"tree": "stale", "read_model": "fresh", "snapshot": "stale"}, "FAIL", id="one_fresh"),
        pytest.param({"tree": "stale", "read_model": "stale", "snapshot": "no_data"}, "FAIL", id="stale_stale_no_data"),
        pytest.param({"tree": "stale", "read_model": "stale", "snapshot": "fresh"}, "FAIL", id="stale_stale_fresh"),
    ],
)
def test_sf1_verdict(probe, answers, verdict):
    got, reason = probe.sf1_verdict(answers)
    assert got == verdict
    for reader, cls in answers.items():
        if verdict == "FAIL" and cls != "stale":
            assert f"{reader}={cls}" in reason  # неожиданный ответ назван в причине


FRESH_LABEL = {"class": "fresh", "age_s": 1.0, "tick_sec": 5.0}


@pytest.mark.parametrize(
    ("labels", "expected_ok", "expected_rows"),
    [
        pytest.param({"processor": FRESH_LABEL}, True, [], id="fresh_ok"),
        pytest.param(
            {"ProcessManager": None, "processor": FRESH_LABEL},
            True,
            ["ProcessManager: no_data (нет метки)"],
            id="no_label_is_report_row",
        ),
        pytest.param(
            {"processor": {"class": "fresh", "age_s": 11.0, "tick_sec": 5.0}},
            False,
            None,  # текст строки сверяем отдельно: «ложная тревога»
            id="older_than_two_ticks_fails",
        ),
    ],
)
def test_sf1_precondition_(probe, labels, expected_ok, expected_rows):
    ok, rows = probe.sf1_precondition(labels)
    assert ok is expected_ok
    if expected_rows is None:
        assert len(rows) == 1
        assert "ложная тревога" in rows[0]
        assert "processor" in rows[0]
    else:
        assert rows == expected_rows


# ---------------------------------------------------------------------------
# SF1: family_stopped_writer на подставном драйвере
# ---------------------------------------------------------------------------

T0 = 1000.0
PID = 100


class FakeClockKill:
    """Часы, сон и `os.kill` в одном месте: сон двигает часы, kill пишет журнал событий."""

    def __init__(self, drv: "StopDriver"):
        self.now = T0
        self.drv = drv
        self.kill_calls: list[tuple[int, int]] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def kill(self, pid: int, sig: int) -> None:
        self.kill_calls.append((pid, sig))
        self.drv.events.append(("kill", sig))
        if sig == signal.SIGSTOP:
            self.drv.frozen_ts = self.now - 1.0  # последняя метка остановленного писателя
        elif sig == signal.SIGCONT:
            self.drv.frozen_ts = None


class StopDriver:
    """Подставной драйвер для `family_stopped_writer` (цель — `processor`, метки у пяти из семи)."""

    def __init__(self, *, pid_after: int = PID, raise_on_read_when_stopped: bool = False):
        self.events: list[tuple] = []
        self.frozen_ts: float | None = None
        self.pid_after = pid_after
        self.raise_on_read = raise_on_read_when_stopped
        self.clock: FakeClockKill | None = None
        self.supervision_calls = 0
        self._telemetry_lock = threading.Lock()
        self._telemetry_model = SimpleNamespace(read=self._model_read)

    def _stopped(self) -> bool:
        return self.frozen_ts is not None

    def _subtree(self, proc: str) -> dict:
        tree: dict[str, Any] = {"state": {"uptime": 3.0}}
        if proc in NO_LABEL:
            return tree
        src_ts = self.frozen_ts if (proc == "processor" and self._stopped()) else self.clock.now - 1.0
        tree["state"]["fps"] = 12.5
        tree["_fresh"] = {"seq": int(self.clock.now), "src_ts": src_ts, "incarnation": "i1", "tick_sec": 5.0}
        return tree

    def _model_read(self, path: str, key: str) -> dict:
        cls = "stale" if (path == "processes.processor" and self._stopped()) else "fresh"
        return {"class": cls, "value": 12.5, "age_s": 11.75 if cls == "stale" else 1.0}

    def send_command(self, process, command, data=None, timeout=None):
        if command == "introspect.status":
            return {"success": True, "result": {"success": True, "process": process, "pid": PID}}
        if command == "state.get_subtree":
            if self.raise_on_read and self._stopped():
                raise RuntimeError("boom")
            self.events.append(("read", data["path"]))
            proc = data["path"].split(".", 1)[1]
            return {"success": True, "result": {"subtree": self._subtree(proc)}}
        return {"success": True, "result": {}}

    def supervision_status(self, process=None, timeout=None):
        self.events.append(("supervision",))
        self.supervision_calls += 1
        pid = PID if self.supervision_calls == 1 else self.pid_after
        procs = {p: {"pid": 500 + i, "instance_restarts": 0} for i, p in enumerate(PROCS)}
        procs["processor"] = {"pid": pid, "instance_restarts": 0}
        return {"success": True, "result": {"processes": procs}}

    def introspect_telemetry(self, process, timeout=None):
        return {"success": True, "result": {"throttle_rules": [{"pattern": "processes.**", "min_interval_s": 1.0}]}}

    def telemetry_snapshot(self, process=None, metric=None):
        cls = "stale" if (process == "processor" and self._stopped()) else "fresh"
        return {
            "success": True,
            "metrics": {f"processes.{process}.state.fps": {"value": 12.5, "class": cls}},
            "gap_count": 0,
        }


def run_sf1(probe, monkeypatch, drv: StopDriver, *, neighbor: str = "processor") -> FakeClockKill:
    monkeypatch.setattr(probe, "ROWS", [])
    monkeypatch.setattr(probe, "NOTES", [])
    roles = {**probe.PROFILE.roles, "neighbor": neighbor}
    monkeypatch.setattr(probe, "PROFILE", dataclasses.replace(probe.PROFILE, roles=roles))
    fake = FakeClockKill(drv)
    drv.clock = fake
    ctx = {"procs": list(PROCS)}
    run_bounded(lambda: probe.family_stopped_writer(drv, ctx, kill=fake.kill, sleep=fake.sleep, clock=fake.clock))
    return fake


def test_sf1_pass_when_target_stops_answering(probe, monkeypatch):
    """Склейка настоящих функций зонда с подставным драйвером: PASS-путь целиком."""
    drv = StopDriver()
    fake = run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "PASS", sf1["observed"]
    assert fake.kill_calls == [(PID, signal.SIGSTOP), (PID, signal.SIGCONT)]
    assert "tree=stale" in sf1["observed"]
    assert "read_model=stale" in sf1["observed"]
    assert "snapshot=stale" in sf1["observed"]


def test_sf1_refuses_process_manager(probe, monkeypatch):
    drv = StopDriver()
    fake = run_sf1(probe, monkeypatch, drv, neighbor="ProcessManager")
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert "ProcessManager" in sf1["observed"]
    assert fake.kill_calls == []


def test_sf1_sigcont_in_finally(probe, monkeypatch):
    drv = StopDriver(raise_on_read_when_stopped=True)
    fake = run_sf1(probe, monkeypatch, drv)  # исключение читателя наружу не уходит
    sf1 = rows_by_id(probe)["SF1"]
    assert fake.kill_calls == [(PID, signal.SIGSTOP), (PID, signal.SIGCONT)]
    assert sf1["verdict"] == "FAIL"
    assert "RuntimeError" in sf1["observed"]
    cont_at = drv.events.index(("kill", signal.SIGCONT))
    last_supervision_at = max(i for i, e in enumerate(drv.events) if e == ("supervision",))
    assert last_supervision_at > cont_at  # снимок «после» снят ПОСЛЕ SIGCONT


def test_sf1_restart_is_unverified(probe, monkeypatch):
    drv = StopDriver(pid_after=200)  # pid у `processor`: 100 до окна, 200 после
    run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert f"{PID}" in sf1["observed"]
    assert "200" in sf1["observed"]
