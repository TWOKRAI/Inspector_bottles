"""Тесты WireStatusMonitor — мониторинг статусов и метрик wire'ов.

Pure Python, без Qt. Тестируем:
- начальный статус (NOT_CONFIGURED)
- on_wire_setup_sent → PENDING
- on_status_received → обновление статуса
- on_wire_teardown_sent → удаление записи
- on_metrics_received → обновление WireMetrics
- check_timeouts → PENDING → BROKEN по таймауту
- get_broken_wires, get_all_statuses (копия), summary
- полный lifecycle: setup → status → metrics → teardown
- on_status_received для неизвестного wire (создать запись)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from multiprocess_prototype.frontend.bridge.wire_monitor import (
    WireMetrics,
    WireStatus,
    WireStatusMonitor,
)


# --- Fixtures ---


@pytest.fixture
def monitor() -> WireStatusMonitor:
    """Монитор с коротким timeout (1 сек) для тестов таймаутов."""
    return WireStatusMonitor(pending_timeout_sec=1.0, poll_interval_ms=500)


# --- Тесты ---


class TestInitialState:

    def test_initial_status_not_configured(self, monitor: WireStatusMonitor) -> None:
        """get_status для неизвестного wire → NOT_CONFIGURED."""
        result = monitor.get_status("unknown_wire")
        assert result == WireStatus.NOT_CONFIGURED

    def test_initial_metrics_none(self, monitor: WireStatusMonitor) -> None:
        """get_metrics для неизвестного wire → None."""
        assert monitor.get_metrics("unknown_wire") is None

    def test_initial_broken_wires_empty(self, monitor: WireStatusMonitor) -> None:
        """get_broken_wires на пустом мониторе → пустой список."""
        assert monitor.get_broken_wires() == []

    def test_initial_summary(self, monitor: WireStatusMonitor) -> None:
        """summary на пустом мониторе → '0 active, 0 pending, 0 broken'."""
        assert monitor.summary() == "0 active, 0 pending, 0 broken"


class TestOnWireSetupSent:

    def test_on_wire_setup_sent_sets_pending(self, monitor: WireStatusMonitor) -> None:
        """on_wire_setup_sent → статус PENDING."""
        monitor.on_wire_setup_sent("wire_A")
        assert monitor.get_status("wire_A") == WireStatus.PENDING

    def test_on_wire_setup_sent_creates_metrics(self, monitor: WireStatusMonitor) -> None:
        """on_wire_setup_sent → создаёт запись WireMetrics."""
        monitor.on_wire_setup_sent("wire_A")
        metrics = monitor.get_metrics("wire_A")
        assert isinstance(metrics, WireMetrics)

    def test_on_wire_setup_sent_records_timestamp(self, monitor: WireStatusMonitor) -> None:
        """on_wire_setup_sent → фиксирует timestamp для timeout-детекции."""
        monitor.on_wire_setup_sent("wire_A")
        assert "wire_A" in monitor._pending_since


class TestOnStatusReceived:

    def test_on_status_received_updates_pending_to_active(
        self, monitor: WireStatusMonitor
    ) -> None:
        """PENDING → ACTIVE после on_status_received."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_status_received("wire_A", "active")
        assert monitor.get_status("wire_A") == WireStatus.ACTIVE

    def test_on_status_received_clears_pending_since(
        self, monitor: WireStatusMonitor
    ) -> None:
        """Выход из PENDING → убрать запись из _pending_since."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_status_received("wire_A", "active")
        assert "wire_A" not in monitor._pending_since

    def test_on_status_received_idle(self, monitor: WireStatusMonitor) -> None:
        """Статус 'idle' корректно парсится."""
        monitor.on_wire_setup_sent("wire_B")
        monitor.on_status_received("wire_B", "idle")
        assert monitor.get_status("wire_B") == WireStatus.IDLE

    def test_on_status_received_unknown_wire(self, monitor: WireStatusMonitor) -> None:
        """Для неизвестного wire on_status_received создаёт запись."""
        monitor.on_status_received("new_wire", "active")
        assert monitor.get_status("new_wire") == WireStatus.ACTIVE
        assert monitor.get_metrics("new_wire") is not None

    def test_on_status_received_invalid_value(self, monitor: WireStatusMonitor) -> None:
        """Неизвестное строковое значение → BROKEN."""
        monitor.on_status_received("wire_X", "garbage_status")
        assert monitor.get_status("wire_X") == WireStatus.BROKEN


class TestOnWireTeardown:

    def test_on_wire_teardown_removes(self, monitor: WireStatusMonitor) -> None:
        """on_wire_teardown_sent удаляет wire из мониторинга."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_wire_teardown_sent("wire_A")
        assert monitor.get_status("wire_A") == WireStatus.NOT_CONFIGURED
        assert monitor.get_metrics("wire_A") is None

    def test_on_wire_teardown_removes_pending_since(
        self, monitor: WireStatusMonitor
    ) -> None:
        """on_wire_teardown_sent очищает _pending_since."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_wire_teardown_sent("wire_A")
        assert "wire_A" not in monitor._pending_since

    def test_on_wire_teardown_unknown_wire_no_error(
        self, monitor: WireStatusMonitor
    ) -> None:
        """Teardown для несуществующего wire не вызывает исключений."""
        monitor.on_wire_teardown_sent("nonexistent")  # не должно кидать


class TestOnMetricsReceived:

    def test_on_metrics_received_updates_fields(
        self, monitor: WireStatusMonitor
    ) -> None:
        """on_metrics_received → обновляет fps, latency_ms, buffer_fill."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_metrics_received("wire_A", {"fps": 25.0, "latency_ms": 12.5, "buffer_fill": 0.75})
        metrics = monitor.get_metrics("wire_A")
        assert metrics is not None
        assert metrics.fps == 25.0
        assert metrics.latency_ms == 12.5
        assert metrics.buffer_fill == 0.75

    def test_on_metrics_received_partial_update(
        self, monitor: WireStatusMonitor
    ) -> None:
        """Частичный словарь → обновляются только переданные поля."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_metrics_received("wire_A", {"fps": 30.0})
        metrics = monitor.get_metrics("wire_A")
        assert metrics is not None
        assert metrics.fps == 30.0
        assert metrics.latency_ms == 0.0  # не трогали

    def test_on_metrics_received_unknown_wire_creates_entry(
        self, monitor: WireStatusMonitor
    ) -> None:
        """Метрики для неизвестного wire → создать запись."""
        monitor.on_metrics_received("new_wire", {"fps": 10.0})
        metrics = monitor.get_metrics("new_wire")
        assert metrics is not None
        assert metrics.fps == 10.0


class TestCheckTimeouts:

    def test_check_timeouts_pending_to_broken(
        self, monitor: WireStatusMonitor
    ) -> None:
        """PENDING > timeout → переводится в BROKEN."""
        monitor.on_wire_setup_sent("wire_A")
        # Мокаем time.time чтобы прошло 2 секунды (timeout=1.0)
        future_time = monitor._pending_since["wire_A"] + 2.0
        with patch("multiprocess_prototype.frontend.bridge.wire_monitor.time.time", return_value=future_time):
            broken = monitor.check_timeouts()
        assert "wire_A" in broken
        assert monitor.get_status("wire_A") == WireStatus.BROKEN

    def test_check_timeouts_no_timeout(self, monitor: WireStatusMonitor) -> None:
        """PENDING < timeout → остаётся PENDING, список пустой."""
        monitor.on_wire_setup_sent("wire_A")
        # Мокаем time.time: прошло только 0.5 сек (timeout=1.0)
        future_time = monitor._pending_since["wire_A"] + 0.5
        with patch("multiprocess_prototype.frontend.bridge.wire_monitor.time.time", return_value=future_time):
            broken = monitor.check_timeouts()
        assert broken == []
        assert monitor.get_status("wire_A") == WireStatus.PENDING

    def test_check_timeouts_clears_pending_since(
        self, monitor: WireStatusMonitor
    ) -> None:
        """После перевода в BROKEN → запись из _pending_since удаляется."""
        monitor.on_wire_setup_sent("wire_A")
        future_time = monitor._pending_since["wire_A"] + 2.0
        with patch("multiprocess_prototype.frontend.bridge.wire_monitor.time.time", return_value=future_time):
            monitor.check_timeouts()
        assert "wire_A" not in monitor._pending_since

    def test_check_timeouts_multiple_wires(
        self, monitor: WireStatusMonitor
    ) -> None:
        """Несколько wire'ов: только просроченные переходят в BROKEN."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_wire_setup_sent("wire_B")
        # wire_A просрочен, wire_B нет
        base_time = monitor._pending_since["wire_A"]
        monitor._pending_since["wire_B"] = base_time + 1.5  # "отправлен позже"
        future_time = base_time + 2.0
        with patch("multiprocess_prototype.frontend.bridge.wire_monitor.time.time", return_value=future_time):
            broken = monitor.check_timeouts()
        assert "wire_A" in broken
        assert "wire_B" not in broken
        assert monitor.get_status("wire_A") == WireStatus.BROKEN
        assert monitor.get_status("wire_B") == WireStatus.PENDING


class TestGetBrokenWires:

    def test_get_broken_wires(self, monitor: WireStatusMonitor) -> None:
        """get_broken_wires возвращает только BROKEN wire'ы."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_wire_setup_sent("wire_B")
        monitor.on_status_received("wire_A", "broken")
        monitor.on_status_received("wire_B", "active")
        broken = monitor.get_broken_wires()
        assert broken == ["wire_A"]

    def test_get_broken_wires_empty_when_all_ok(
        self, monitor: WireStatusMonitor
    ) -> None:
        """get_broken_wires → [] если нет сломанных."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_status_received("wire_A", "active")
        assert monitor.get_broken_wires() == []


class TestGetAllStatuses:

    def test_get_all_statuses_copy(self, monitor: WireStatusMonitor) -> None:
        """get_all_statuses возвращает копию, не ссылку на внутренний dict."""
        monitor.on_wire_setup_sent("wire_A")
        snapshot = monitor.get_all_statuses()
        # Мутируем snapshot — внутренний dict не должен измениться
        snapshot["wire_A"] = WireStatus.BROKEN
        assert monitor.get_status("wire_A") == WireStatus.PENDING

    def test_get_all_statuses_contains_all(
        self, monitor: WireStatusMonitor
    ) -> None:
        """get_all_statuses содержит все зарегистрированные wire'ы."""
        monitor.on_wire_setup_sent("wire_A")
        monitor.on_wire_setup_sent("wire_B")
        monitor.on_status_received("wire_B", "active")
        statuses = monitor.get_all_statuses()
        assert "wire_A" in statuses
        assert "wire_B" in statuses
        assert statuses["wire_B"] == WireStatus.ACTIVE


class TestSummary:

    def test_summary_format(self, monitor: WireStatusMonitor) -> None:
        """summary → '1 active, 1 pending, 0 broken'."""
        monitor.on_wire_setup_sent("wire_A")             # PENDING
        monitor.on_wire_setup_sent("wire_B")             # PENDING → ACTIVE
        monitor.on_status_received("wire_B", "active")
        result = monitor.summary()
        assert result == "1 active, 1 pending, 0 broken"

    def test_summary_with_broken(self, monitor: WireStatusMonitor) -> None:
        """summary считает BROKEN wire'ы."""
        monitor.on_status_received("wire_A", "broken")
        result = monitor.summary()
        assert "1 broken" in result

    def test_summary_empty(self, monitor: WireStatusMonitor) -> None:
        """summary без wire'ов → все нули."""
        assert monitor.summary() == "0 active, 0 pending, 0 broken"


class TestFullLifecycle:

    def test_lifecycle_full_cycle(self, monitor: WireStatusMonitor) -> None:
        """Полный цикл: setup → status ACTIVE → metrics → teardown."""
        # Шаг 1: отправка setup
        monitor.on_wire_setup_sent("wire_cam")
        assert monitor.get_status("wire_cam") == WireStatus.PENDING

        # Шаг 2: runtime подтвердил создание
        monitor.on_status_received("wire_cam", "active")
        assert monitor.get_status("wire_cam") == WireStatus.ACTIVE

        # Шаг 3: пришли метрики
        monitor.on_metrics_received("wire_cam", {"fps": 30.0, "latency_ms": 5.0})
        metrics = monitor.get_metrics("wire_cam")
        assert metrics is not None
        assert metrics.fps == 30.0

        # Шаг 4: teardown
        monitor.on_wire_teardown_sent("wire_cam")
        assert monitor.get_status("wire_cam") == WireStatus.NOT_CONFIGURED
        assert monitor.get_metrics("wire_cam") is None
