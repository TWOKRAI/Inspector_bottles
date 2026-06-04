"""
Тесты для ProcessMonitor.

Проверяют:
- start/stop
- Обнаружение изменения состояния
- Broadcast при изменении
- Ошибка в цикле мониторинга
"""

import time
from unittest.mock import MagicMock
from multiprocessing import Event

from ..monitor.process_monitor import ProcessMonitor


def _make_mock_process_manager():
    """Создать mock ProcessManagerProcess."""
    mock_pm = MagicMock()
    mock_pm.name = "ProcessManager"
    mock_pm.shared_resources = MagicMock()
    mock_pm.router_manager = MagicMock()
    mock_pm.communication = MagicMock()
    mock_pm.worker_manager = MagicMock()

    # Настраиваем worker_manager.create_worker для запуска функции напрямую
    def create_worker(name, func, config, auto_start=False):
        pass

    mock_pm.worker_manager.create_worker = create_worker
    return mock_pm


class TestProcessMonitorInit:
    def test_init_defaults(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        assert monitor.poll_interval == 0.5
        assert monitor._monitoring is False
        assert monitor.previous_states == {}

    def test_init_custom_poll_interval(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm, poll_interval=1.0)
        assert monitor.poll_interval == 1.0


class TestProcessMonitorStartStop:
    def test_start_sets_monitoring_flag(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor.start()
        assert monitor._monitoring is True

    def test_start_twice_does_not_duplicate(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor.start()
        monitor.start()
        # Второй вызов логирует warning, но не создаёт второй worker
        mock_pm._log_warning.assert_called()

    def test_stop_clears_monitoring_flag(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor.start()
        monitor.stop()
        assert monitor._monitoring is False

    def test_stop_without_start_does_not_raise(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor.stop()


class TestProcessMonitorStateDetection:
    def test_handle_state_change_logs_status_change(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)

        previous = {"status": "running", "metadata": {}, "custom": {}}
        current = {"status": "stopped", "metadata": {}, "custom": {}}

        monitor._handle_state_change("TestProcess", previous, current)
        mock_pm._log_info.assert_called()

    def test_handle_state_change_broadcasts_on_status_change(self) -> None:
        mock_pm = _make_mock_process_manager()
        mock_pm.communication.broadcast.return_value = 1
        monitor = ProcessMonitor(mock_pm)

        previous = {"status": "running", "metadata": {}, "custom": {}}
        current = {"status": "error", "metadata": {}, "custom": {}}

        monitor._handle_state_change("TestProcess", previous, current)
        mock_pm.communication.broadcast.assert_called_once()

    def test_handle_state_change_no_broadcast_if_no_router(self) -> None:
        mock_pm = _make_mock_process_manager()
        mock_pm.router_manager = None
        mock_pm.communication.broadcast.return_value = 0
        monitor = ProcessMonitor(mock_pm)

        previous = {"status": "running", "metadata": {}, "custom": {}}
        current = {"status": "stopped", "metadata": {}, "custom": {}}

        monitor._handle_state_change("TestProcess", previous, current)

    def test_broadcast_status_change_message_format(self) -> None:
        mock_pm = _make_mock_process_manager()
        mock_pm.communication.broadcast.return_value = 1
        monitor = ProcessMonitor(mock_pm)

        monitor._broadcast_status_change("P1", "running", "stopped", {"status": "stopped"})

        call_args = mock_pm.communication.broadcast.call_args
        message = call_args[0][0]
        assert message["type"] == "system"
        assert message["subtype"] == "process_status_changed"
        assert message["process_name"] == "P1"
        assert message["old_status"] == "running"
        assert message["new_status"] == "stopped"

    def test_broadcast_skipped_if_no_router(self) -> None:
        mock_pm = _make_mock_process_manager()
        mock_pm.router_manager = None
        monitor = ProcessMonitor(mock_pm)

        monitor._broadcast_status_change("P1", "running", "stopped", {})
        mock_pm.communication.broadcast.assert_not_called()


class TestProcessMonitorHeartbeats:
    def test_check_heartbeats_marks_crashed(self) -> None:
        mock_pm = _make_mock_process_manager()
        dead_proc = MagicMock()
        dead_proc.is_alive.return_value = False
        dead_proc.exitcode = -9
        dead_proc.name = "DeadP"
        mock_registry = MagicMock()
        mock_registry.os_processes = [dead_proc]
        mock_pm._process_registry = mock_registry
        mock_pm.shared_resources.process_state_registry = MagicMock()

        monitor = ProcessMonitor(mock_pm)
        monitor._check_heartbeats()

        assert monitor.previous_states.get("DeadP", {}).get("status") == "crashed"
        mock_pm.shared_resources.process_state_registry.update_state.assert_called()


class TestProcessMonitorGetStats:
    def test_get_stats_returns_dict(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        stats = monitor.get_stats()
        assert isinstance(stats, dict)
        assert "monitoring" in stats
        assert "tracked_processes" in stats
        assert "poll_interval" in stats
        assert "crashed_processes" in stats

    def test_get_stats_reflects_state(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor.previous_states = {"P1": {}, "P2": {}}
        stats = monitor.get_stats()
        assert stats["tracked_processes"] == 2
        assert stats["monitoring"] is False


class TestProcessMonitorLoop:
    def test_monitoring_loop_handles_exception_gracefully(self) -> None:
        """Ошибка в цикле мониторинга не прерывает цикл."""
        mock_pm = _make_mock_process_manager()
        mock_pm.shared_resources.process_state_registry.get_all_process_data.side_effect = RuntimeError("test error")
        monitor = ProcessMonitor(mock_pm, poll_interval=0.01)

        stop_event = Event()
        pause_event = Event()

        # Запускаем цикл на короткое время
        import threading

        def run_loop():
            monitor._monitoring_loop(stop_event, pause_event)

        t = threading.Thread(target=run_loop)
        t.start()
        time.sleep(0.05)
        stop_event.set()
        t.join(timeout=1.0)

        # Цикл должен был завершиться без исключения
        assert not t.is_alive()


class TestProcessMonitorStatePublish:
    """Публикация live-телеметрии в StateStore (Фаза 1.1)."""

    def test_publish_state_calls_state_store_manager(self) -> None:
        mock_pm = _make_mock_process_manager()
        ssm = MagicMock()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm)

        monitor._publish_state("processes.cam.state.status", "running")

        ssm.handle_state_set.assert_called_once()
        arg = ssm.handle_state_set.call_args[0][0]
        assert arg["data"]["path"] == "processes.cam.state.status"
        assert arg["data"]["value"] == "running"
        assert arg["data"]["source"] == "ProcessMonitor"

    def test_publish_state_noop_without_state_store(self) -> None:
        mock_pm = _make_mock_process_manager()
        mock_pm._state_store_manager = None
        monitor = ProcessMonitor(mock_pm)
        # Не должно бросать исключение
        monitor._publish_state("processes.x.state.status", "running")

    def test_heartbeat_does_not_publish_telemetry(self) -> None:
        """Task 2: heartbeat НЕ публикует телеметрию в дерево (это self-publish процесса).

        Монитор лишь хранит workers_status (для legacy full-status broadcast) и
        обновляет liveness/timeout — никаких processes.X.workers.* / state.fps.
        """
        mock_pm = _make_mock_process_manager()
        ssm = MagicMock()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm)

        monitor._on_heartbeat_received(
            {
                "sender": "cam0",
                "timestamp": 1.0,
                "workers_status": {"w1": {"status": "running", "effective_hz": 12.5}},
            }
        )

        paths = {c[0][0]["data"]["path"] for c in ssm.handle_state_set.call_args_list}
        assert not any(p.startswith("processes.cam0.workers.") for p in paths)
        assert "processes.cam0.state.fps" not in paths
        # liveness обновлён, workers_status сохранён для broadcast.
        assert monitor._last_heartbeat["cam0"] == 1.0
        assert monitor._workers_status["cam0"] == {"w1": {"status": "running", "effective_hz": 12.5}}

    def test_status_change_publishes_process_state(self) -> None:
        mock_pm = _make_mock_process_manager()
        ssm = MagicMock()
        mock_pm._state_store_manager = ssm
        mock_pm.router_manager = None  # broadcast пропустится, publish идёт первым
        monitor = ProcessMonitor(mock_pm)

        monitor._broadcast_status_change("cam0", "created", "running", {"status": "running"})

        paths = {c[0][0]["data"]["path"] for c in ssm.handle_state_set.call_args_list}
        assert "processes.cam0.state.status" in paths


def _published(ssm: MagicMock) -> dict:
    """Собрать {path: value} из всех вызовов handle_state_set."""
    return {c[0][0]["data"]["path"]: c[0][0]["data"]["value"] for c in ssm.handle_state_set.call_args_list}


class TestSystemHealth:
    """Task 3.2 — system.health.active/avg_fps/broken_wires."""

    def test_active_counts_running_processes(self) -> None:
        mock_pm = _make_mock_process_manager()
        ssm = MagicMock()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm)

        all_states = {
            "cam0": {"status": "running"},
            "cam1": {"status": "running"},
            "proc": {"status": "stopped"},
        }
        monitor._publish_health(all_states)

        pub = _published(ssm)
        assert pub["system.health.active"] == 2
        assert pub["system.health.broken_wires"] == 0

    def test_active_zero_when_none_running(self) -> None:
        mock_pm = _make_mock_process_manager()
        ssm = MagicMock()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm)

        monitor._publish_health({"proc": {"status": "stopped"}})

        pub = _published(ssm)
        assert pub["system.health.active"] == 0
        # avg_fps не публикуется без данных
        assert "system.health.avg_fps" not in pub

    def test_avg_fps_averages_selfpublished_fps(self) -> None:
        """avg_fps = среднее по self-опубликованным processes.X.state.fps (running)."""
        from multiprocess_framework.modules.state_store_module import StateStoreManager

        ssm = StateStoreManager(initial_state={}, logger=None)
        mock_pm = _make_mock_process_manager()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm)

        # Эмулируем self-publish процессов в дерево.
        for path, val in {
            "processes.cam0.state.fps": 20.0,
            "processes.cam1.state.fps": 10.0,
            "processes.cam_stopped.state.fps": 99.0,
        }.items():
            ssm.handle_state_set({"data": {"path": path, "value": val, "source": "test"}})

        monitor._publish_health(
            {
                "cam0": {"status": "running"},
                "cam1": {"status": "running"},
                "cam_stopped": {"status": "stopped"},
            }
        )

        assert ssm.handle_state_get({"data": {"path": "system.health.active"}})["value"] == 2
        # (20 + 10) / 2 = 15.0; остановленный cam_stopped исключён
        assert ssm.handle_state_get({"data": {"path": "system.health.avg_fps"}})["value"] == 15.0

    def test_health_avg_fps_skipped_without_selfpublished_fps(self) -> None:
        """Нет ни одного опубликованного fps → avg_fps не публикуется (карточка «—»)."""
        from multiprocess_framework.modules.state_store_module import StateStoreManager

        ssm = StateStoreManager(initial_state={}, logger=None)
        mock_pm = _make_mock_process_manager()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm)

        monitor._publish_health({"cam0": {"status": "running"}})

        assert ssm.handle_state_get({"data": {"path": "system.health.active"}})["value"] == 1
        assert ssm.handle_state_get({"data": {"path": "system.health.avg_fps"}})["status"] == "error"


class TestHealthIntegrationRealStore:
    """Интеграция с реальным StateStoreManager: health читает self-публикованный fps."""

    def test_health_reads_selfpublished_fps_from_real_tree(self) -> None:
        from multiprocess_framework.modules.state_store_module import StateStoreManager

        ssm = StateStoreManager(initial_state={}, logger=None)
        mock_pm = _make_mock_process_manager()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm)

        # Self-publish процесса (как делает ProcessHeartbeat._publish_metrics_to_tree).
        ssm.handle_state_set({"data": {"path": "processes.cam0.state.fps", "value": 25.0, "source": "cam0"}})

        monitor._publish_health({"cam0": {"status": "running"}})

        # health агрегирует из дерева (не «—»/0).
        assert ssm.handle_state_get({"data": {"path": "system.health.active"}})["value"] == 1
        assert ssm.handle_state_get({"data": {"path": "system.health.avg_fps"}})["value"] == 25.0
        assert ssm.handle_state_get({"data": {"path": "system.health.broken_wires"}})["value"] == 0
