"""Fault-тесты CapturePlugin: contain → report → degrade (Ф2 Task 2.4).

Синтетический отказ камеры: ``_cap.read()`` кидает исключение →
``produce()`` возвращает [] (воркер НЕ падает), счётчик ``HealthState.errors``
растёт, после порога подряд-ошибок breaker открывается → status degraded.

Hardware-gated часть acceptance (физически выдернуть камеру + FPS-замер)
остаётся за живым стендом (зафиксировано с Ф0).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_framework.modules.process_module.health import (
    DEFAULT_FAIL_THRESHOLD,
    HealthField,
    HealthReporter,
    HealthState,
    HealthStatus,
    LastErrorKey,
)
from Plugins.sources.capture.plugin import CapturePlugin


def _make_faulty_plugin() -> tuple[CapturePlugin, HealthState]:
    """Собрать плагин с реальным health и камерой, кидающей исключение."""
    state = HealthState(log_only=False)
    ctx = MagicMock()
    ctx.config = {"resolution_width": 320, "resolution_height": 240}
    ctx.health = HealthReporter(state, source="capture")

    plugin = CapturePlugin()
    plugin.configure(ctx)

    cap = MagicMock()
    cap.read.side_effect = RuntimeError("камера выдернута (синтетика)")
    plugin._cap = cap
    plugin._is_capturing = True
    return plugin, state


class TestProduceFault:
    """Отказ _cap.read(): contain → report."""

    def test_produce_contains_exception(self):
        """Исключение в _cap.read() → produce() возвращает [], НЕ падает."""
        plugin, _state = _make_faulty_plugin()

        assert plugin.produce() == []

    def test_errors_counter_grows(self):
        """Каждый отказ produce() инкрементит HealthState.errors (честный счётчик)."""
        plugin, state = _make_faulty_plugin()

        for _ in range(3):
            plugin.produce()

        assert state.error_count == 3

    def test_last_error_recorded_with_context(self):
        """last_error содержит тип исключения и context сайта (M-err-2)."""
        plugin, state = _make_faulty_plugin()

        plugin.produce()

        snap = state.snapshot()
        last = snap[HealthField.LAST_ERROR]
        assert last is not None
        assert last[LastErrorKey.TYPE] == "RuntimeError"
        assert last[LastErrorKey.CONTEXT].startswith("capture:")


class TestBreakerDegrade:
    """После порога подряд-ошибок breaker открывается → degrade."""

    def test_breaker_opens_after_threshold(self):
        """threshold подряд-отказов → breaker open, status degraded."""
        plugin, state = _make_faulty_plugin()

        for _ in range(DEFAULT_FAIL_THRESHOLD):
            assert plugin.produce() == []  # ни один вызов не падает

        assert state.breaker_state == "open"
        assert state.status == HealthStatus.DEGRADED

    def test_breaker_closed_below_threshold(self):
        """До порога breaker закрыт, статус не деградирует."""
        plugin, state = _make_faulty_plugin()

        for _ in range(DEFAULT_FAIL_THRESHOLD - 1):
            plugin.produce()

        assert state.breaker_state == "closed"
        assert state.status == HealthStatus.OK
