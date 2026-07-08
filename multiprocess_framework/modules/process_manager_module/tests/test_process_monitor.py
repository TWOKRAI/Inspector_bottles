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

from ..core.restart_policy import RestartPolicy
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


class TestForgetProcess:
    """forget_process — очистка служебной истории имени при cleanup (Task 1.4)."""

    def test_forget_clears_all_name_history(self) -> None:
        """Все словари истории имени очищены; чужие имена не тронуты."""
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor._last_heartbeat = {"cam": 1.0, "other": 2.0}
        monitor._restart_history = {"cam": [1.0, 2.0, 3.0], "other": [1.0]}
        monitor._workers_status = {"cam": {"w": {}}, "other": {}}
        monitor._first_seen = {"cam": 10.0, "other": 20.0}
        monitor.previous_states = {"cam": {"status": "running"}, "other": {"status": "running"}}
        monitor._pending_restarts = {"cam": 0.0, "other": 0.0}

        monitor.forget_process("cam")

        for d in (
            monitor._last_heartbeat,
            monitor._restart_history,
            monitor._workers_status,
            monitor._first_seen,
            monitor.previous_states,
            monitor._pending_restarts,
        ):
            assert "cam" not in d
            assert "other" in d

    def test_forget_unknown_name_is_noop(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor.forget_process("ghost")  # не должно бросить


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

    def test_start_resets_stale_heartbeat_on_resume(self) -> None:
        """Resume после паузы (replace_blueprint) перезапускает heartbeat-таймер.

        Регресс-гард (command-result-bridge): простой паузы монитора не должен
        засчитываться как пропущенный heartbeat → ложный UNRESPONSIVE → shutdown
        системы (краш GUI по SIGTERM). После start() устаревшие метки сброшены к ~now.
        """
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        stale = time.time() - 999.0
        monitor._last_heartbeat = {"camera_0": stale, "gui": stale}

        monitor.start()  # resume

        for name, ts in monitor._last_heartbeat.items():
            assert time.time() - ts < 5.0, f"heartbeat '{name}' не сброшен при resume"

    def test_loop_idles_when_paused(self) -> None:
        """stop()-пауза (_monitoring=False): цикл НЕ опрашивает реестр / heartbeat.

        Суть фикса краша: во время replace_blueprint монитор на паузе не выполняет
        _check_heartbeats → нет ложного UNRESPONSIVE → нет shutdown системы.
        """
        import threading

        mock_pm = _make_mock_process_manager()
        reg = mock_pm.shared_resources.process_state_registry
        monitor = ProcessMonitor(mock_pm, poll_interval=0.01)
        monitor._monitoring = False  # пауза (как после stop())

        stop_event = Event()
        pause_event = Event()
        t = threading.Thread(target=lambda: monitor._monitoring_loop(stop_event, pause_event))
        t.start()
        time.sleep(0.05)
        stop_event.set()
        t.join(timeout=1.0)

        reg.get_all_process_data.assert_not_called()  # тело цикла пропущено на паузе

    def test_resume_does_not_create_second_worker(self) -> None:
        """start→stop→start: воркер цикла создаётся один раз (resume = снятие паузы)."""
        mock_pm = _make_mock_process_manager()
        mock_pm.worker_manager.create_worker = MagicMock()
        monitor = ProcessMonitor(mock_pm)

        monitor.start()
        monitor.stop()
        monitor.start()  # resume

        assert mock_pm.worker_manager.create_worker.call_count == 1
        assert monitor._monitoring is True


class TestProcessMonitorProtectedAutoRestart:
    """command-result-bridge: авто-рестарт НЕ трогает protected (GUI/PM)."""

    def test_auto_restart_skips_protected(self) -> None:
        mock_pm = _make_mock_process_manager()
        mock_pm._get_protected_names.return_value = {"gui", "ProcessManager"}
        monitor = ProcessMonitor(mock_pm, restart_policy=RestartPolicy(enabled=True))

        monitor._try_auto_restart("gui", reason="unresponsive")

        mock_pm.restart_process.assert_not_called()
        mock_pm._log_warning.assert_called()

    def test_auto_restart_allows_non_protected(self) -> None:
        """Не-protected: рестарт планируется и уходит IPC-командой в PM (Task 3.1).

        Прямой restart_process на потоке монитора запрещён — гонка с
        apply_topology; команда исполнится на message_processor-потоке.
        """
        mock_pm = _make_mock_process_manager()
        mock_pm.name = "ProcessManager"
        mock_pm._get_protected_names.return_value = {"gui"}
        mock_pm.communication.send_message.return_value = True
        monitor = ProcessMonitor(mock_pm, restart_policy=RestartPolicy(enabled=True, backoff_sec=0.0))

        monitor._try_auto_restart("camera_0", reason="crashed")

        # НЕ прямой вызов — только план
        mock_pm.restart_process.assert_not_called()
        assert "camera_0" in monitor._pending_restarts

        monitor._dispatch_due_restarts()

        mock_pm.restart_process.assert_not_called()
        target, msg = mock_pm.communication.send_message.call_args[0]
        assert target == "ProcessManager"
        assert msg["data"] == {"cmd": "process.restart", "process_name": "camera_0"}
        assert monitor._pending_restarts == {}

    def test_pending_restart_not_dispatched_before_backoff(self) -> None:
        """До истечения backoff рестарт не диспатчится."""
        mock_pm = _make_mock_process_manager()
        mock_pm._get_protected_names.return_value = set()
        monitor = ProcessMonitor(mock_pm, restart_policy=RestartPolicy(enabled=True, backoff_sec=60.0))

        monitor._try_auto_restart("camera_0", reason="crashed")
        monitor._dispatch_due_restarts()

        mock_pm.communication.send_message.assert_not_called()
        assert "camera_0" in monitor._pending_restarts

    def test_forget_process_cancels_pending_restart(self) -> None:
        """Cleanup имени (switch) отменяет его отложенный рестарт."""
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor._pending_restarts["old_cam"] = 0.0

        monitor.forget_process("old_cam")

        assert monitor._pending_restarts == {}


class TestRestartWindow:
    """Ф3.6: окно стабильности N/T — метки протухают, счётчик не пожизненный."""

    def _monitor(self, **policy_kw):
        mock_pm = _make_mock_process_manager()
        mock_pm.name = "ProcessManager"
        mock_pm._get_protected_names.return_value = set()
        mock_pm.communication.send_message.return_value = True
        pol = RestartPolicy(enabled=True, backoff_sec=0.0, **policy_kw)
        return mock_pm, ProcessMonitor(mock_pm, restart_policy=pol)

    def test_giveup_after_max_retries_in_window(self) -> None:
        """N рестартов в окне → give-up (status failed), больше не планируем."""
        mock_pm, monitor = self._monitor(max_retries=3, window_sec=60.0)

        for _ in range(3):
            monitor._try_auto_restart("cam", reason="crashed")
            monitor._dispatch_due_restarts()  # снять pending, чтобы след. попытка прошла

        # 4-я попытка — give-up
        monitor._try_auto_restart("cam", reason="crashed")

        assert monitor.previous_states["cam"]["status"] == "failed"
        assert "cam" not in monitor._pending_restarts

    def test_expired_marks_reset_counter(self) -> None:
        """Метки старше window протухли → счётчик обнулился, рестарт продолжается."""
        mock_pm, monitor = self._monitor(max_retries=3, window_sec=10.0)

        # Три «старых» метки (протухшие относительно окна 10с)
        old = time.monotonic() - 999.0
        monitor._restart_history["cam"] = [old, old, old]

        monitor._try_auto_restart("cam", reason="crashed")

        # Протухшие метки не считаются → это первая попытка в окне, НЕ give-up
        assert monitor.previous_states.get("cam", {}).get("status") != "failed"
        assert "cam" in monitor._pending_restarts
        # В истории осталась только свежая метка
        assert len(monitor._restart_history["cam"]) == 1

    def test_window_zero_is_lifetime_counter(self) -> None:
        """window_sec=0 → пожизненный счётчик (метки не протухают)."""
        mock_pm, monitor = self._monitor(max_retries=2, window_sec=0.0)

        # Даже очень старые метки считаются при window_sec=0
        old = time.monotonic() - 9999.0
        monitor._restart_history["cam"] = [old, old]

        monitor._try_auto_restart("cam", reason="crashed")

        assert monitor.previous_states["cam"]["status"] == "failed"

    def test_giveup_publishes_health_failed(self) -> None:
        """Ф3.6: give-up публикует processes.<name>.health.status=failed в дерево."""
        from multiprocess_framework.modules.state_store_module import StateStoreManager

        ssm = StateStoreManager(initial_state={}, logger=None)
        mock_pm = _make_mock_process_manager()
        mock_pm.name = "ProcessManager"
        mock_pm._get_protected_names.return_value = set()
        mock_pm._state_store_manager = ssm
        monitor = ProcessMonitor(mock_pm, restart_policy=RestartPolicy(enabled=True, max_retries=1, window_sec=0.0))

        # Уже исчерпан лимит (одна метка при max_retries=1) → следующая = give-up
        monitor._restart_history["cam"] = [time.monotonic()]
        monitor._try_auto_restart("cam", reason="crashed")

        assert ssm.handle_state_get({"data": {"path": "processes.cam.health.status"}})["value"] == "failed"
        reason = ssm.handle_state_get({"data": {"path": "processes.cam.health.degraded_reason"}})["value"]
        assert "give-up" in reason
        assert ssm.handle_state_get({"data": {"path": "processes.cam.health.updated_at"}})["status"] == "ok"


class TestPerProcessPolicy:
    """Ф3.6: per-process RestartPolicy перекрывает глобальную (_resolve_policy)."""

    def test_per_process_enables_when_global_disabled(self) -> None:
        """Глобальная выключена, но per-process source включена → рестарт планируется."""
        mock_pm = _make_mock_process_manager()
        mock_pm.name = "ProcessManager"
        mock_pm._get_protected_names.return_value = set()
        mock_pm.communication.send_message.return_value = True
        # Реальный dict конфигов: у camera_0 есть per-process restart_policy
        mock_pm._process_configs = {
            "camera_0": {"class": "X", "restart_policy": {"enabled": True, "backoff_sec": 0.0}},
            "worker_0": {"class": "Y"},  # без policy → глобальная
        }
        # Глобальная политика ВЫКЛючена
        monitor = ProcessMonitor(mock_pm, restart_policy=RestartPolicy(enabled=False))

        monitor._try_auto_restart("camera_0", reason="crashed")
        assert "camera_0" in monitor._pending_restarts  # per-process включила

        monitor._try_auto_restart("worker_0", reason="crashed")
        assert "worker_0" not in monitor._pending_restarts  # глобальная выключена

    def test_resolve_policy_fallback_to_global(self) -> None:
        """Пустой/битый restart_policy → глобальная политика."""
        mock_pm = _make_mock_process_manager()
        mock_pm._process_configs = {
            "a": {"class": "X", "restart_policy": {}},  # пустой → глобальная
            "b": {"class": "X", "restart_policy": "broken"},  # не dict → глобальная
        }
        global_pol = RestartPolicy(enabled=True, max_retries=7)
        monitor = ProcessMonitor(mock_pm, restart_policy=global_pol)

        assert monitor._resolve_policy("a") is global_pol
        assert monitor._resolve_policy("b") is global_pol
        assert monitor._resolve_policy("unknown") is global_pol

    def test_per_process_max_retries_overrides(self) -> None:
        """per-process max_retries=1 → give-up быстрее глобальной."""
        mock_pm = _make_mock_process_manager()
        mock_pm.name = "ProcessManager"
        mock_pm._get_protected_names.return_value = set()
        mock_pm.communication.send_message.return_value = True
        mock_pm._process_configs = {
            "hub": {"class": "X", "restart_policy": {"enabled": True, "max_retries": 1, "window_sec": 0.0}},
        }
        monitor = ProcessMonitor(mock_pm, restart_policy=RestartPolicy(enabled=True, max_retries=99))

        monitor._restart_history["hub"] = [time.monotonic()]  # уже 1 попытка
        monitor._try_auto_restart("hub", reason="crashed")

        assert monitor.previous_states["hub"]["status"] == "failed"  # give-up при max_retries=1


class TestMonitorSyncPause:
    """Task 3.1: stop(wait=True) дожидается завершения текущей итерации."""

    def test_stop_waits_for_inflight_iteration(self) -> None:
        import threading
        import time as _time

        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor._monitoring = True

        # Имитация идущей итерации: замок держится другим потоком 0.2с
        monitor._iteration_lock.acquire()

        def _release_later() -> None:
            _time.sleep(0.2)
            monitor._iteration_lock.release()

        t = threading.Thread(target=_release_later)
        t.start()

        t0 = _time.monotonic()
        monitor.stop()
        elapsed = _time.monotonic() - t0
        t.join()

        assert elapsed >= 0.15, "stop() не дождался завершения итерации"
        assert monitor._monitoring is False

    def test_stop_timeout_logs_warning_and_returns(self) -> None:
        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor._monitoring = True
        monitor._iteration_lock.acquire()  # никто не отпустит

        monitor.stop(timeout=0.1)

        assert monitor._monitoring is False
        mock_pm._log_warning.assert_called()
        monitor._iteration_lock.release()

    def test_stop_no_wait_returns_immediately(self) -> None:
        import time as _time

        mock_pm = _make_mock_process_manager()
        monitor = ProcessMonitor(mock_pm)
        monitor._monitoring = True
        monitor._iteration_lock.acquire()

        t0 = _time.monotonic()
        monitor.stop(wait=False)
        elapsed = _time.monotonic() - t0

        assert elapsed < 0.05
        assert monitor._monitoring is False
        monitor._iteration_lock.release()


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
        # subtype удалён (§11.3): диспетчеризация идёт по type/process_name,
        # не по внесхемному subtype. Контракт статус-сообщения — поля ниже.
        assert "subtype" not in message
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

    def test_unresponsive_disabled_policy_does_not_shutdown(self) -> None:
        """Unresponsive при выключенной policy НЕ роняет систему (consistency с crashed).

        Регресс-гард (command-result-bridge): транзиентный unresponsive (например
        новый процесс после горячей замены ещё не прислал heartbeat) НЕ должен
        каскадом инициировать shutdown и ронять GUI.
        """
        mock_pm = _make_mock_process_manager()
        mock_pm._stop_requested = False
        # policy.enabled=False по умолчанию
        monitor = ProcessMonitor(mock_pm, heartbeat_timeout=1.0)
        monitor._last_heartbeat["cam"] = time.time() - 999.0
        monitor.previous_states["cam"] = {"status": "running", "metadata": {}, "custom": {}}

        monitor._check_heartbeat_timeout("cam", time.time())

        assert mock_pm._stop_requested is False  # система НЕ остановлена
        # процесс помечен unresponsive
        assert monitor.previous_states["cam"]["status"] == "unresponsive"


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
        monitor._monitoring = True  # gate цикла: иначе тело (и путь исключения) пропускается

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
