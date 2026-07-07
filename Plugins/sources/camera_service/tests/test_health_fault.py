"""Fault-тесты CameraServicePlugin: contain → report → degrade (Ф2 Task 2.4).

Синтетический отказ backend'а: ``capture_frame()`` кидает исключение →
``produce()`` возвращает [] (воркер НЕ падает), счётчик ``HealthState.errors``
растёт, после порога подряд-ошибок breaker открывается → status degraded.
Плюс сайт записи register-поля: невалидное значение → report, команда не падает.
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
from Plugins.sources.camera_service.plugin import CameraServicePlugin


def _make_plugin_with_health(config: dict | None = None) -> tuple[CameraServicePlugin, HealthState]:
    """Собрать плагин с реальным health поверх mock-контекста."""
    state = HealthState(log_only=False)
    ctx = MagicMock()
    ctx.config = config or {"camera_type": "simulator"}
    ctx.health = HealthReporter(state, source="camera_service")

    plugin = CameraServicePlugin()
    plugin.configure(ctx)
    return plugin, state


def _make_faulty_plugin() -> tuple[CameraServicePlugin, HealthState]:
    """Плагин с backend'ом, кидающим исключение из capture_frame()."""
    plugin, state = _make_plugin_with_health()
    backend = MagicMock()
    backend.capture_frame.side_effect = RuntimeError("backend умер (синтетика)")
    plugin._backend = backend
    plugin._is_capturing = True
    return plugin, state


class TestProduceFault:
    """Отказ backend.capture_frame(): contain → report (M-err-1)."""

    def test_produce_contains_exception(self):
        """Исключение в capture_frame() → produce() возвращает [], НЕ падает."""
        plugin, _state = _make_faulty_plugin()

        assert plugin.produce() == []

    def test_errors_counter_grows(self):
        """Каждый отказ produce() инкрементит HealthState.errors (честный счётчик)."""
        plugin, state = _make_faulty_plugin()

        for _ in range(3):
            plugin.produce()

        assert state.error_count == 3

    def test_last_error_recorded_with_context(self):
        """last_error содержит тип исключения и context с типом backend'а."""
        plugin, state = _make_faulty_plugin()

        plugin.produce()

        snap = state.snapshot()
        last = snap[HealthField.LAST_ERROR]
        assert last is not None
        assert last[LastErrorKey.TYPE] == "RuntimeError"
        assert last[LastErrorKey.CONTEXT].startswith("camera_service:")
        assert "simulator" in last[LastErrorKey.CONTEXT]


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


class TestApplyFieldFault:
    """Невалидное значение register-поля: contain → report."""

    def test_invalid_register_value_reported(self):
        """setattr с невалидным значением → report_error, команда не падает."""
        plugin, state = _make_plugin_with_health()

        # fps: int — строка не пройдёт валидацию pydantic (validate_assignment)
        result = plugin._apply_field("fps", "не число")

        assert result is False  # backend'а нет → live-применение невозможно
        assert state.error_count == 1
        snap = state.snapshot()
        assert snap[HealthField.LAST_ERROR][LastErrorKey.TYPE] == "ValidationError"

    def test_register_value_unchanged_after_fault(self):
        """Невалидная запись не меняет register-поле (остаётся дефолт)."""
        plugin, state = _make_plugin_with_health()

        plugin._apply_field("fps", "не число")

        assert plugin._reg.fps == 25
        assert state.status == HealthStatus.OK  # одиночная ошибка не деградирует
