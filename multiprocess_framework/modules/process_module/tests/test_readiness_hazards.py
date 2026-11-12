# -*- coding: utf-8 -*-
"""Task 1.2 (system-run-state) — hazard-тесты автора: снимок готовности и его публикация (форма, защёлка, потоки, темп).

Не слепой набор (``test_readiness_hook.py``/``test_readiness_publish.py``) — свойства, которые автор гарантирует:
форма причин и потолки; ``failure``/``check_function`` блокируют, ``out_of_spec``/``maintenance`` нет; защёлка «объявил
готовность» не превращает ``worker.pause_all`` в потерю готовности; процесс БЕЗ плагинов тоже публикует снимок;
heartbeat не ждёт ``readiness()``; ``at`` растёт, пока процесс жив, и застывает, когда он остановлен; темп ≤ 2 Гц;
heartbeat получает КОПИЮ снимка.

Стенд — настоящий ``PluginOrchestrator`` + ``MockProcessServices`` (форма), настоящие процессы под
``run_process_function`` в daemon-потоке (потоки, темп, защёлка); ожидания — циклы с дедлайном.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.health import schema
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

_THIS = "multiprocess_framework.modules.process_module.tests.test_readiness_hazards"
_PROC = "rhz_proc"
_JOIN_S = 30.0

GATE = threading.Event()
ENTERED = threading.Event()


@pytest.fixture(autouse=True)
def _reset() -> Any:
    GATE.clear()
    ENTERED.clear()
    HzRet.value = []
    yield
    GATE.set()


class HzPlain(ProcessModulePlugin):
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class HzRet(HzPlain):
    """``readiness()`` возвращает то, что положил тест в ``HzRet.value``."""

    name = "hz_ret"
    value: Any = []

    def readiness(self, ctx: PluginContext) -> Any:
        return HzRet.value


class HzBlockReadiness(HzPlain):
    name = "hz_block_readiness"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        ENTERED.set()
        GATE.wait(_JOIN_S)
        return []


def _snapshot_of(*classes: type, status: str = "running") -> tuple[PluginOrchestrator, MockProcessServices]:
    services = MockProcessServices(name=_PROC)
    services._current_process_status = status  # type: ignore[attr-defined]
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name} for c in classes]
    )
    orch.boot()
    return orch, services


# --------------------------------------------------------------------------- #
# T7, T15, T17, T11: форма причин, потолки, блокирующие уровни
# --------------------------------------------------------------------------- #

_BAD_SHAPE = {
    "node": f"{_PROC}.hz_ret",
    "severity": "failure",
    "reason": "readiness() вернул неверную форму",
    "source": "readiness",
}


@pytest.mark.parametrize(
    "value",
    [
        None,
        "x",
        [1],
        [{"severity": "bogus", "reason": "r"}],
        [{"severity": "failure", "reason": 5}],
        [{"reason": "r"}],
        [{"severity": "out_of_spec", "reason": "ok"}, "не dict"],
    ],
    ids=["none", "str", "list-of-int", "bad-severity", "reason-not-str", "no-severity", "one-good-one-bad"],
)
def test_malformed_readiness_return(value: Any) -> None:
    """Неверная форма возврата -> ровно одна ``failure`` «readiness() вернул неверную форму»; ``ready`` ложно."""
    HzRet.value = value
    orch, _ = _snapshot_of(HzRet)

    snap = orch.readiness_snapshot()

    assert snap["reasons"] == [_BAD_SHAPE], snap
    assert snap["ready"] is False


def test_reason_length_and_count_capped() -> None:
    """Текст причины <= 200 символов, причин <= 32 (с маркером «причин больше 32»); ``ready`` считан до обрезки."""
    HzRet.value = [{"severity": "out_of_spec", "reason": "x" * 500} for _ in range(40)]
    orch, _ = _snapshot_of(HzRet)

    snap = orch.readiness_snapshot()

    assert len(snap["reasons"]) == 32, len(snap["reasons"])
    assert all(len(r["reason"]) <= 200 for r in snap["reasons"])
    assert snap["reasons"][-1] == {
        "node": _PROC,
        "severity": "out_of_spec",
        "reason": "причин больше 32",
        "source": "readiness",
    }
    assert snap["ready"] is True  # одни out_of_spec не блокируют

    # блокирующая причина за пределом потолка: не теряется ни в ready, ни в списке
    HzRet.value = [{"severity": "out_of_spec", "reason": "o"} for _ in range(39)] + [
        {"severity": "failure", "reason": "камера"}
    ]
    capped = orch.readiness_snapshot()
    assert capped["ready"] is False
    assert any(r["severity"] == "failure" and r["reason"] == "камера" for r in capped["reasons"]), capped["reasons"]
    assert len(capped["reasons"]) == 32


def test_check_function_blocks_ready_maintenance_does_not() -> None:
    """``check_function`` блокирует готовность (К3), ``maintenance`` и ``out_of_spec`` — нет."""
    orch, _ = _snapshot_of(HzRet)

    HzRet.value = [{"severity": "check_function", "reason": "самопроверка"}]
    blocked = orch.readiness_snapshot()
    assert blocked["ready"] is False
    assert [r["severity"] for r in blocked["reasons"]] == ["check_function"]

    HzRet.value = [{"severity": "maintenance", "reason": "ТО"}, {"severity": "out_of_spec", "reason": "дрейф"}]
    free = orch.readiness_snapshot()
    assert free["ready"] is True
    assert [r["severity"] for r in free["reasons"]] == ["maintenance", "out_of_spec"]


def test_failure_reason_blocks_ready_even_with_health_log_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MULTIPROCESS_HEALTH_LOG_ONLY=1`` глушит здоровье, но не готовность."""
    monkeypatch.setenv("MULTIPROCESS_HEALTH_LOG_ONLY", "1")
    HzRet.value = [{"severity": "failure", "reason": "камера не отвечает"}]
    orch, _ = _snapshot_of(HzRet)

    snap = orch.readiness_snapshot()

    assert snap["ready"] is False
    assert [r["reason"] for r in snap["reasons"]] == ["камера не отвечает"]


def test_not_ready_before_announce() -> None:
    """Пока процесс не объявил готовность (``initializing``), ``ready`` ложно; ``running``/``paused`` — истинно."""
    orch, services = _snapshot_of(HzRet, status="initializing")
    assert orch.readiness_snapshot()["ready"] is False
    assert orch.readiness_snapshot(announced=True)["ready"] is True  # защёлку держит вызывающий и передаёт явно
    services._current_process_status = "running"  # type: ignore[attr-defined]
    assert orch.readiness_snapshot()["ready"] is True
    services._current_process_status = "paused"  # type: ignore[attr-defined]
    assert orch.readiness_snapshot()["ready"] is True
    assert orch.readiness_snapshot(announced=False)["ready"] is False


# --------------------------------------------------------------------------- #
# T16: пути листа
# --------------------------------------------------------------------------- #


def test_readiness_paths_literal() -> None:
    """Пути и ключи листа ``processes.<n>.readiness`` — литералы (читатель и издатель — PM, Task 1.3)."""
    assert schema.readiness_root("cam0") == "processes.cam0.readiness"
    assert schema.readiness_path("cam0", schema.ReadinessField.PAUSED) == "processes.cam0.readiness.paused"
    assert schema.READINESS_FIELDS == ("ready", "reasons", "paused", "at")
    assert schema.READINESS_REASON_KEYS == ("node", "severity", "reason", "source")


# --------------------------------------------------------------------------- #
# T20: heartbeat получает копию
# --------------------------------------------------------------------------- #


class _HbServices:
    def __init__(self, snapshot: dict | None) -> None:
        self.name = "hb_proc"
        self.worker_manager = None
        self._readiness_snapshot = snapshot
        self.sent: list[dict] = []

    def send_message(self, target: str, message: dict) -> bool:
        self.sent.append(message)
        return True

    def get_config(self, key: str, default=None):
        return default

    def log_info(self, msg: str, **kw) -> None: ...

    def log_debug(self, msg: str, **kw) -> None: ...


def test_heartbeat_gets_copy_of_snapshot() -> None:
    """Правка поля ``readiness`` в сообщении не меняет снимок процесса (разные потоки делят снимок)."""
    snapshot = {
        "ready": False,
        "reasons": [{"node": "a.b", "severity": "failure", "reason": "r", "source": "readiness"}],
        "paused": False,
        "at": 1.5,
    }
    services = _HbServices(snapshot)

    ProcessHeartbeat(services)._send_heartbeat({})  # type: ignore[arg-type]
    sent = services.sent[0]["readiness"]
    sent["reasons"].append({"x": 1})
    sent["ready"] = True

    assert services._readiness_snapshot == {
        "ready": False,
        "reasons": [{"node": "a.b", "severity": "failure", "reason": "r", "source": "readiness"}],
        "paused": False,
        "at": 1.5,
    }


def test_heartbeat_without_snapshot_has_no_readiness_field() -> None:
    """Снимка ещё нет -> поля ``readiness`` в сообщении нет (PM по молчанию считает не готов)."""
    services = _HbServices(None)

    ProcessHeartbeat(services)._send_heartbeat({})  # type: ignore[arg-type]

    assert "readiness" not in services.sent[0]


# --------------------------------------------------------------------------- #
# Настоящие процессы: T4-подобное, T6, T12, T13, T18, T19
# --------------------------------------------------------------------------- #

SHARED: dict[str, Any] = {"event": None, "proc": None}


class PlainProcess(ProcessModule):
    """Настоящий ``ProcessModule`` БЕЗ плагинов (как ``HeadlessGuiProcess`` рецепта)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self


class PluginGenericProcess(GenericProcess):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self


def _start(process_cls: str, plugin_classes: list[type], event: Any) -> tuple[threading.Thread, threading.Event, Any]:
    SHARED["event"] = event
    SHARED["proc"] = None
    plugins = [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name} for c in plugin_classes]
    cfg = {"config": {"plugins": plugins, "chain_targets": []}}
    own_ready = multiprocessing.Event()
    bundle = {
        "queues": {"data": multiprocessing.Queue()},
        "config": cfg,
        "custom": {"process_config": cfg, "ready_event": own_ready},
    }
    stop = threading.Event()
    thread = threading.Thread(
        target=run_process_function,
        args=(f"{_THIS}.{process_cls}", "rhz_real", stop, bundle, None),
        daemon=True,
        name="rhz-real-process",
    )
    thread.start()
    return thread, stop, own_ready


def _wait(predicate: Any, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _snap() -> dict | None:
    proc = SHARED["proc"]
    return None if proc is None else proc._readiness_snapshot


def _stop(thread: threading.Thread, stop: threading.Event) -> None:
    stop.set()
    thread.join(_JOIN_S)
    assert not thread.is_alive(), "run_process_function не вышел после stop"


@pytest.mark.timeout(120)
def test_process_without_orchestrator_publishes_ready_shape() -> None:
    """Процесс БЕЗ плагинов: снимок есть, ``ready`` = защёлка, ``reasons`` пусто, ``paused`` следует за событием."""
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start("PlainProcess", [], event)
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил готовность"
        assert SHARED["proc"]._orchestrator is None
        assert _wait(lambda: (_snap() or {}).get("ready") is True, 5.0), _snap()
        snap = _snap()
        assert sorted(snap) == ["at", "paused", "ready", "reasons"], snap
        assert snap["reasons"] == [] and snap["paused"] is False and isinstance(snap["at"], float), snap

        event.clear()
        assert _wait(lambda: _snap()["paused"] is True, 5.0), "после clear() paused не стал истинным"
        assert _snap()["ready"] is True
        event.set()
        assert _wait(lambda: _snap()["paused"] is False, 5.0), "после set() paused не стал ложным"
    finally:
        _stop(thread, stop)


@pytest.mark.timeout(120)
def test_ready_stays_true_after_worker_pause_all() -> None:
    """Защёлка: после ``worker.pause_all`` и любого статуса процесса ``ready`` не падает и снимок живёт."""
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start("PlainProcess", [], event)
    try:
        assert own_ready.wait(_JOIN_S)
        assert _wait(lambda: (_snap() or {}).get("ready") is True, 5.0), _snap()
        proc = SHARED["proc"]

        proc.worker_manager.pause_all_workers(exclude_system=True)
        proc._current_process_status = "paused"  # как ставит builtin_commands worker.pause_all
        at_before = _snap()["at"]
        assert _wait(lambda: _snap()["at"] > at_before, 5.0), "снимок не обновляется после pause_all"
        assert _snap()["ready"] is True

        # защёлка, а не членство: статус вне {running, paused} готовность не снимает
        proc._current_process_status = "initializing"
        at_mid = _snap()["at"]
        assert _wait(lambda: _snap()["at"] > at_mid, 5.0)
        assert _snap()["ready"] is True
    finally:
        _stop(thread, stop)


@pytest.mark.timeout(120)
def test_snapshot_at_grows_while_alive_and_goes_stale_when_stopped() -> None:
    """``at`` растёт, пока процесс жив; после остановки застывает (по нему PM судит «молчание», Task 1.3)."""
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start("PlainProcess", [], event)
    try:
        assert own_ready.wait(_JOIN_S)
        assert _wait(lambda: _snap() is not None, 5.0)
        first = _snap()["at"]
        assert _wait(lambda: _snap()["at"] > first, 3.0), "at не растёт у живого процесса"
    finally:
        _stop(thread, stop)
    frozen = _snap()["at"]
    time.sleep(1.2)
    assert _snap()["at"] == frozen, "at растёт у остановленного процесса (поток снимка не остановлен)"


@pytest.mark.timeout(120)
def test_snapshot_rate_at_most_2hz() -> None:
    """Темп расчёта снимка <= 2 Гц: за 2,2 с не больше 5 разных ``at`` (2 Гц * 2,2 с + граница)."""
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start("PlainProcess", [], event)
    try:
        assert own_ready.wait(_JOIN_S)
        assert _wait(lambda: _snap() is not None, 5.0)
        seen: set[float] = set()
        end = time.monotonic() + 2.2
        while time.monotonic() < end:
            seen.add(_snap()["at"])
            time.sleep(0.01)
    finally:
        _stop(thread, stop)
    assert 2 <= len(seen) <= 5, sorted(seen)


@pytest.mark.timeout(120)
def test_blocking_readiness_does_not_stall_heartbeat() -> None:
    """Зависший ``readiness()`` плагина не задерживает heartbeat: сообщение уходит за < 1 с."""
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start("PluginGenericProcess", [HzBlockReadiness], event)
    try:
        assert own_ready.wait(_JOIN_S)
        assert ENTERED.wait(10.0), "readiness() не вызван потоком снимка"
        proc = SHARED["proc"]
        sent: list[dict] = []
        proc.send_message = lambda target, message: sent.append(message) or True  # type: ignore[method-assign]

        sender = threading.Thread(target=lambda: proc._heartbeat._send_heartbeat({}), daemon=True, name="rhz-hb")
        started = time.monotonic()
        sender.start()
        sender.join(1.0)

        assert not sender.is_alive(), "heartbeat ждёт зависший readiness()"
        assert time.monotonic() - started < 1.0
        assert sent and sent[0]["command"] == "heartbeat"
        assert "readiness" not in sent[0], "снимка ещё нет (первый расчёт завис) — поле должно отсутствовать"

        GATE.set()  # первый расчёт начат до RUNNING: ready догонит со 2-го такта
        assert _wait(lambda: (_snap() or {}).get("ready") is True, 5.0), _snap()
        proc._heartbeat._send_heartbeat({})
        assert sent[-1]["readiness"]["ready"] is True, sent[-1]
    finally:
        GATE.set()
        _stop(thread, stop)


@pytest.mark.timeout(120)
def test_paused_flag_follows_event_within_budget() -> None:
    """``paused`` в снимке меняется <= 0,8 с после ``clear()``/``set()`` (0,05 с сверка + 0,5 с снимок + запас).

    Heartbeat с ``heartbeat_interval = 0,2`` добавляет не больше такта: бюджет приёмки 1.2 — <= 1 с целиком.
    """
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start("PluginGenericProcess", [HzRet], event)
    try:
        assert own_ready.wait(_JOIN_S)
        assert _wait(lambda: (_snap() or {}).get("paused") is False, 5.0), _snap()
        for target_paused, change in ((True, event.clear), (False, event.set)):
            started = time.monotonic()
            change()
            assert _wait(lambda: _snap()["paused"] is target_paused, 3.0), f"paused не стал {target_paused}"
            elapsed = time.monotonic() - started
            assert elapsed <= 0.8, f"paused стал {target_paused} через {elapsed:.2f} с (> 0,8 с)"
    finally:
        _stop(thread, stop)
