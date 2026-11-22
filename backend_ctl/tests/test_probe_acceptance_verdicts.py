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
#: На Windows `signal.SIGSTOP` нет — тесты с настоящими номерами сигналов там не имеют смысла.
needs_sigstop = pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="нет signal.SIGSTOP на этой платформе")


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

    def __init__(
        self,
        *,
        pid_after: int = PID,
        raise_on_read_when_stopped: bool = False,
        introspect_pid: int = PID,
        tick_sec: float = 5.0,
        pre_bad: tuple[str, str] | None = None,
    ):
        """`pre_bad = (читатель, класс)` — у живого `inspector` ДО стопа этот читатель отвечает не `fresh`."""
        self.introspect_pid = introspect_pid
        self.tick_sec = tick_sec
        self.pre_bad = pre_bad
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
        if proc == "inspector" and self.pre_bad is not None and self.pre_bad[0] == "tree":
            src_ts = self.clock.now - 30.0  # метка живого процесса устарела
        tree["state"]["fps"] = 12.5
        tree["_fresh"] = {"seq": int(self.clock.now), "src_ts": src_ts, "incarnation": "i1", "tick_sec": self.tick_sec}
        return tree

    def _pre_class(self, reader: str, proc: str) -> str | None:
        if self.pre_bad is not None and self.pre_bad[0] == reader and proc == "inspector" and not self._stopped():
            return self.pre_bad[1]
        return None

    def _model_read(self, path: str, key: str) -> dict:
        cls = self._pre_class("read_model", path.split(".", 1)[1]) or (
            "stale" if (path == "processes.processor" and self._stopped()) else "fresh"
        )
        return {"class": cls, "value": 12.5, "age_s": 11.75 if cls == "stale" else 1.0}

    def send_command(self, process, command, data=None, timeout=None):
        if command == "introspect.status":
            return {"success": True, "result": {"success": True, "process": process, "pid": self.introspect_pid}}
        if command == "state.get_subtree":
            if self.raise_on_read and self._stopped():
                raise RuntimeError("boom")
            self.events.append(("read", data["path"]))
            proc = data["path"].split(".", 1)[1]
            # Форма настоящего обработчика (state_store_manager.py:379-385): value и revision, ключа subtree нет.
            payload = {"status": "ok", "request_id": "r1", "value": self._subtree(proc), "revision": 7}
            return {"success": True, "result": payload}
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
        cls = self._pre_class("snapshot", process) or (
            "stale" if (process == "processor" and self._stopped()) else "fresh"
        )
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


@needs_sigstop
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


@needs_sigstop
def test_sf1_refuses_process_manager(probe, monkeypatch):
    drv = StopDriver()
    fake = run_sf1(probe, monkeypatch, drv, neighbor="ProcessManager")
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert "ProcessManager" in sf1["observed"]
    assert fake.kill_calls == []


@needs_sigstop
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


@needs_sigstop
def test_sf1_restart_is_unverified(probe, monkeypatch):
    drv = StopDriver(pid_after=200)  # pid у `processor`: 100 до окна, 200 после
    run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert f"{PID}" in sf1["observed"]
    assert "200" in sf1["observed"]


# ---------------------------------------------------------------------------
# SF1: поздняя защита стопа, прерывание по предусловию, такт, платформа
# ---------------------------------------------------------------------------

OWN_PID, PM_PID = 77, 500


@pytest.mark.parametrize(
    ("target", "pid", "reason_part"),
    [
        pytest.param(None, 100, "нет роли neighbor", id="target_none"),
        pytest.param("ProcessManager", 100, "ProcessManager", id="target_is_pm"),
        pytest.param("processor", None, "pid цели", id="pid_none"),
        pytest.param("processor", 0, "pid цели", id="pid_0"),
        pytest.param("processor", 1, "pid цели", id="pid_1"),
        pytest.param("processor", -1, "pid цели", id="pid_minus_1"),
        pytest.param("processor", True, "pid цели", id="pid_bool"),
        pytest.param("processor", "4242", "pid цели", id="pid_str"),
        pytest.param("processor", OWN_PID, "сам зонд", id="pid_is_probe"),
        pytest.param("processor", PM_PID, "совпадает с pid ProcessManager", id="pid_is_pm_pid"),
        pytest.param("processor", 100, None, id="normal_pid"),
    ],
)
def test_sf1_target_guard(probe, target, pid, reason_part):
    reason = probe.sf1_target_guard(target, "ProcessManager", pid, OWN_PID, PM_PID)
    if reason_part is None:
        assert reason is None
    else:
        assert reason is not None
        assert reason_part in reason


def test_sf1_target_guard_pm_pid_unknown(probe):
    """pid ProcessManager из супервизии может отсутствовать — тогда защита по имени, а нормальный pid допустим."""
    assert probe.sf1_target_guard("processor", "ProcessManager", 100, OWN_PID, None) is None


@needs_sigstop
@pytest.mark.parametrize(
    ("introspect_pid", "reason_part"),
    [
        pytest.param(1, "pid цели", id="pid_1"),
        pytest.param(500, "совпадает с pid ProcessManager", id="pid_of_pm"),  # 500 — pid PM в StopDriver
    ],
)
def test_sf1_refuses_dangerous_pid_in_full_path(probe, monkeypatch, introspect_pid, reason_part):
    drv = StopDriver(introspect_pid=introspect_pid)
    fake = run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert reason_part in sf1["observed"]
    assert fake.kill_calls == []


@needs_sigstop
def test_sf1_refuses_pid_mismatch(probe, monkeypatch):
    drv = StopDriver(introspect_pid=4242)  # супервизия говорит 100
    fake = run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert "4242" in sf1["observed"]
    assert "100" in sf1["observed"]
    assert fake.kill_calls == []


@needs_sigstop
@pytest.mark.parametrize(
    ("reader", "cls"),
    [
        pytest.param("tree", "stale", id="tree_stale"),
        pytest.param("read_model", "stale", id="read_model_stale"),
        pytest.param("read_model", "no_data", id="read_model_no_data"),
        pytest.param("snapshot", "stale", id="snapshot_stale"),
        pytest.param("snapshot", "no_data", id="snapshot_no_data"),
    ],
)
def test_sf1_precondition_failure_aborts_before_sigstop(probe, monkeypatch, reader, cls):
    drv = StopDriver(pre_bad=(reader, cls))
    fake = run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "FAIL"
    assert "ложная тревога" in sf1["observed"]
    if reader != "tree":
        assert f"inspector: {reader}={cls}" in sf1["observed"]
    assert fake.kill_calls == []


@needs_sigstop
def test_sf1_refuses_tick_other_than_five(probe, monkeypatch):
    drv = StopDriver(tick_sec=10.0)
    fake = run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert "окно рассчитано на такт 5.0" in sf1["observed"]
    assert fake.kill_calls == []
    assert fake.now - T0 < 30.0  # сон ограничен: не 2 × 10.0 + 0.5 и не больше окна


def test_sf1_without_sigstop_is_unverified(probe, monkeypatch):
    monkeypatch.delattr(probe.signal, "SIGSTOP", raising=False)
    drv = StopDriver()
    fake = run_sf1(probe, monkeypatch, drv)
    sf1 = rows_by_id(probe)["SF1"]
    assert sf1["verdict"] == "UNVERIFIED"
    assert "SIGSTOP" in sf1["observed"]
    assert fake.kill_calls == []
