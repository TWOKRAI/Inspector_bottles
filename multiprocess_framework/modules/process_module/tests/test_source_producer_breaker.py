# -*- coding: utf-8 -*-
"""produce()-breaker в SourceProducer (Ф2 Task 2.2).

Гоняем ограниченный run_loop (fake-плагин сам ставит stop_event после N вызовов)
и проверяем: подряд-фейлы produce() открывают честный breaker процесса → health
degraded; успешный produce() восстанавливает. breaker_backoff=0 — без реального сна.
"""

from __future__ import annotations

import threading

from multiprocess_framework.modules.process_module.generic.source_producer import (
    SourceProducer,
)
from multiprocess_framework.modules.process_module.health import (
    BreakerState,
    CircuitBreaker,
    HealthReporter,
    HealthState,
    HealthStatus,
)


class _FakePlugin:
    """Source-плагин с управляемым produce(): падает/отдаёт по сценарию.

    scenario — список: exc (RuntimeError) бросить, либо list (вернуть items).
    Итерации сверх сценария повторяют последний шаг. stop_event ставится после
    исчерпания сценария — цикл останавливается детерминированно.
    """

    is_source = True

    def __init__(self, name: str, scenario: list, stop_event: threading.Event) -> None:
        self.name = name
        self._scenario = scenario
        self._stop = stop_event
        self.calls = 0

    def produce(self):
        i = self.calls
        self.calls += 1
        step = self._scenario[i] if i < len(self._scenario) else self._scenario[-1]
        if self.calls >= len(self._scenario):
            self._stop.set()  # последний шаг сценария — дальше не крутим
        if isinstance(step, BaseException):
            raise step
        return step


def _producer(plugin, health: HealthReporter | None) -> SourceProducer:
    return SourceProducer(
        plugin=plugin,
        shm_middleware=None,
        send_fn=lambda target, msg: None,
        chain_targets=[],
        target_fps=1000.0,  # интервал ~1мс — быстрые итерации
        node_name="cam0",
        health=health,
        breaker_backoff_sec=0.0,  # без реального сна при открытом breaker
    )


def _health(threshold: int = 3) -> tuple[HealthState, HealthReporter]:
    hs = HealthState(breaker=CircuitBreaker(fail_threshold=threshold))
    return hs, HealthReporter(hs, source="cam0")


def _run(producer: SourceProducer, stop_event: threading.Event) -> None:
    pause = threading.Event()
    producer.run_loop(stop_event, pause)


def test_consecutive_produce_failures_open_breaker_degrade() -> None:
    stop = threading.Event()
    hs, reporter = _health(threshold=3)
    plugin = _FakePlugin("cam0", [RuntimeError("dead")] * 3, stop)
    _run(_producer(plugin, reporter), stop)

    assert plugin.calls == 3
    assert hs.breaker_state == BreakerState.OPEN
    assert hs.status == HealthStatus.DEGRADED
    assert hs.error_count == 3
    snap = hs.snapshot()
    assert "produce:cam0" in (snap["last_error"] or {}).get("context", "")


def test_successful_produce_recovers_breaker() -> None:
    stop = threading.Event()
    hs, reporter = _health(threshold=2)
    # 2 фейла (open) → успех (record_success закрывает breaker) → пустой (стоп).
    plugin = _FakePlugin("cam0", [RuntimeError("x"), RuntimeError("y"), [], []], stop)
    _run(_producer(plugin, reporter), stop)

    assert hs.breaker_state == BreakerState.CLOSED
    assert hs.status == HealthStatus.OK
    # errors кумулятивный — 2 фейла зафиксированы навсегда.
    assert hs.error_count == 2


def test_no_health_still_runs_backward_compat() -> None:
    # health=None → поведение как раньше: produce() падает, items=[], без краха.
    stop = threading.Event()
    plugin = _FakePlugin("cam0", [RuntimeError("x"), RuntimeError("y")], stop)
    _run(_producer(plugin, None), stop)
    assert plugin.calls == 2  # цикл отработал без исключений наружу


def test_below_threshold_stays_ok() -> None:
    stop = threading.Event()
    hs, reporter = _health(threshold=5)
    plugin = _FakePlugin("cam0", [RuntimeError("x"), RuntimeError("y")], stop)
    _run(_producer(plugin, reporter), stop)
    assert hs.status == HealthStatus.OK
    assert hs.breaker_state == BreakerState.CLOSED
