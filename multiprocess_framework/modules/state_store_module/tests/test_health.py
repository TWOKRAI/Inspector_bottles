"""test_health.py — тесты для HealthMonitor (Task 4g.3).

Покрывает:
- Регистрацию и снятие процессов
- record_activity() → обновление last_seen
- check() → статусы "unknown", "running", "unresponsive"
- Восстановление: unresponsive → running
- overall health: ok / degraded / critical
- Запись результатов в TreeStore
- get_health() — snapshot без пересчёта
- watched_processes — список зарегистрированных
"""
from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.health.monitor import (
    HealthMonitor,
    WatchedProcess,
    STATUS_RUNNING,
    STATUS_UNRESPONSIVE,
    STATUS_UNKNOWN,
    OVERALL_OK,
    OVERALL_DEGRADED,
    OVERALL_CRITICAL,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def store() -> TreeStore:
    return TreeStore()


@pytest.fixture
def monitor(store: TreeStore) -> HealthMonitor:
    """Монитор с коротким таймаутом для быстрых тестов."""
    return HealthMonitor(store, heartbeat_timeout=0.1)


# ---------------------------------------------------------------------------
# 1. Регистрация и watched_processes
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_adds_process(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        assert "camera_0" in monitor.watched_processes

    def test_register_multiple_processes(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")
        assert set(monitor.watched_processes) == {"camera_0", "renderer"}

    def test_unregister_removes_process(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.unregister("camera_0")
        assert "camera_0" not in monitor.watched_processes

    def test_unregister_nonexistent_is_safe(self, monitor: HealthMonitor) -> None:
        # Не должно бросать исключение
        monitor.unregister("ghost_process")

    def test_register_overwrites_pattern(self, monitor: HealthMonitor) -> None:
        """Повторная регистрация обновляет паттерн."""
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("camera_0", "cameras.0.new_state.**")
        # Только один процесс с этим именем
        assert monitor.watched_processes.count("camera_0") == 1


# ---------------------------------------------------------------------------
# 2. record_activity — обновление last_seen
# ---------------------------------------------------------------------------

class TestRecordActivity:
    def test_record_activity_matches_correct_process(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")

        monitor.record_activity("cameras.0.state.actual_fps")

        health = monitor.check()
        assert health["camera_0"] == STATUS_RUNNING
        # renderer никогда не обновлял state
        assert health["renderer"] == STATUS_UNKNOWN

    def test_record_activity_unknown_path_is_ignored(
        self, monitor: HealthMonitor
    ) -> None:
        """Путь без совпадающего процесса — не должен вызывать ошибку."""
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.record_activity("some.other.path.value")
        # camera_0 не получил активность
        health = monitor.check()
        assert health["camera_0"] == STATUS_UNKNOWN

    def test_record_activity_updates_last_seen(
        self, monitor: HealthMonitor
    ) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        before = time.monotonic()
        monitor.record_activity("cameras.0.state.status")
        after = time.monotonic()

        proc = monitor._watched["camera_0"]
        assert proc.last_seen is not None
        assert before <= proc.last_seen <= after


# ---------------------------------------------------------------------------
# 3. check() — статусы процессов
# ---------------------------------------------------------------------------

class TestCheck:
    def test_unknown_without_activity(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        health = monitor.check()
        assert health["camera_0"] == STATUS_UNKNOWN

    def test_running_after_recent_activity(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.record_activity("cameras.0.state.actual_fps")
        health = monitor.check()
        assert health["camera_0"] == STATUS_RUNNING

    def test_unresponsive_after_timeout(self, monitor: HealthMonitor) -> None:
        """Активность была, но timeout истёк."""
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.record_activity("cameras.0.state.actual_fps")
        # Ждём истечения timeout (0.1 сек)
        time.sleep(0.15)
        health = monitor.check()
        assert health["camera_0"] == STATUS_UNRESPONSIVE

    def test_check_returns_all_processes(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")
        health = monitor.check()
        assert set(health.keys()) == {"camera_0", "renderer"}


# ---------------------------------------------------------------------------
# 4. Восстановление: unresponsive → running
# ---------------------------------------------------------------------------

class TestRecovery:
    def test_recovery_from_unresponsive(self, monitor: HealthMonitor) -> None:
        """Процесс был unresponsive, затем снова обновил state → running."""
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.record_activity("cameras.0.state.actual_fps")

        # Ждём timeout
        time.sleep(0.15)
        health = monitor.check()
        assert health["camera_0"] == STATUS_UNRESPONSIVE

        # Процесс восстановился
        monitor.record_activity("cameras.0.state.actual_fps")
        health = monitor.check()
        assert health["camera_0"] == STATUS_RUNNING


# ---------------------------------------------------------------------------
# 5. Overall health
# ---------------------------------------------------------------------------

class TestOverallHealth:
    def test_overall_ok_all_running(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")
        monitor.record_activity("cameras.0.state.fps")
        monitor.record_activity("renderer.state.frame")
        monitor.check()
        assert store.get("system.health.overall") == OVERALL_OK

    def test_overall_degraded_one_unresponsive(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")
        monitor.record_activity("cameras.0.state.fps")
        monitor.record_activity("renderer.state.frame")

        time.sleep(0.15)
        # Только camera_0 восстановился
        monitor.record_activity("cameras.0.state.fps")
        monitor.check()

        assert store.get("system.health.overall") == OVERALL_DEGRADED

    def test_overall_critical_all_unresponsive(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")
        monitor.record_activity("cameras.0.state.fps")
        monitor.record_activity("renderer.state.frame")

        time.sleep(0.15)
        monitor.check()

        assert store.get("system.health.overall") == OVERALL_CRITICAL

    def test_overall_critical_all_unknown(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        """Нет ни одной активности → все unknown → critical."""
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")
        monitor.check()
        assert store.get("system.health.overall") == OVERALL_CRITICAL

    def test_overall_ok_empty_monitor(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        """Нет зарегистрированных процессов → overall ok."""
        monitor.check()
        assert store.get("system.health.overall") == OVERALL_OK


# ---------------------------------------------------------------------------
# 6. Запись в TreeStore
# ---------------------------------------------------------------------------

class TestTreeStoreWrites:
    def test_check_writes_individual_statuses(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.register("renderer", "renderer.state.**")
        monitor.record_activity("cameras.0.state.fps")
        monitor.check()

        assert store.get("system.health.camera_0") == STATUS_RUNNING
        assert store.get("system.health.renderer") == STATUS_UNKNOWN

    def test_check_writes_overall(
        self, monitor: HealthMonitor, store: TreeStore
    ) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.record_activity("cameras.0.state.fps")
        monitor.check()
        assert store.get("system.health.overall") == OVERALL_OK


# ---------------------------------------------------------------------------
# 7. get_health() — snapshot без пересчёта
# ---------------------------------------------------------------------------

class TestGetHealth:
    def test_get_health_empty_before_check(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        # check() не вызывался
        assert monitor.get_health() == {}

    def test_get_health_returns_last_snapshot(self, monitor: HealthMonitor) -> None:
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.record_activity("cameras.0.state.fps")
        health = monitor.check()

        # get_health() должен совпадать с результатом check()
        assert monitor.get_health() == health

    def test_get_health_does_not_recalculate(
        self, monitor: HealthMonitor
    ) -> None:
        """get_health() возвращает старый snapshot, даже если timeout истёк."""
        monitor.register("camera_0", "cameras.0.state.**")
        monitor.record_activity("cameras.0.state.fps")
        first_check = monitor.check()
        assert first_check["camera_0"] == STATUS_RUNNING

        # Ждём timeout — но check() НЕ вызываем
        time.sleep(0.15)

        # get_health() должен отдавать старый snapshot (running), не пересчитывать
        snapshot = monitor.get_health()
        assert snapshot["camera_0"] == STATUS_RUNNING


# ---------------------------------------------------------------------------
# 8. WatchedProcess dataclass
# ---------------------------------------------------------------------------

class TestWatchedProcess:
    def test_watched_process_defaults(self) -> None:
        proc = WatchedProcess(name="test", pattern="test.**")
        assert proc.last_seen is None
        assert proc.status == STATUS_UNKNOWN

    def test_watched_process_fields(self) -> None:
        proc = WatchedProcess(
            name="camera_0",
            pattern="cameras.0.**",
            last_seen=1234.5,
            status=STATUS_RUNNING,
        )
        assert proc.name == "camera_0"
        assert proc.pattern == "cameras.0.**"
        assert proc.last_seen == 1234.5
        assert proc.status == STATUS_RUNNING
