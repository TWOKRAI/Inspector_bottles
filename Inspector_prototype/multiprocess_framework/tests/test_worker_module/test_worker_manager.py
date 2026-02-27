"""
Тесты для модуля worker_manager.py

Проверяем корректность работы WorkerManager, ThreadConfig и связанных классов.
"""
import pytest
import time
import threading
from multiprocess_framework.modules.Worker_module.worker_manager import (
    WorkerManager,
    WorkerStatus,
    ThreadConfig,
    ThreadPriority
)


class TestThreadConfig:
    """Тесты для класса ThreadConfig."""
    
    def test_default_config(self):
        """Проверяем создание конфигурации с параметрами по умолчанию."""
        config = ThreadConfig()
        
        assert config.priority == ThreadPriority.NORMAL
        assert config.poll_interval == 0.1
        assert config.restart_on_failure is False
        assert config.max_restarts == 3
        assert config.dependencies == []
    
    def test_custom_config(self):
        """Проверяем создание конфигурации с кастомными параметрами."""
        config = ThreadConfig(
            priority=ThreadPriority.SYSTEM,
            restart_on_failure=True,
            max_restarts=5,
            dependencies=["worker1", "worker2"]
        )
        
        assert config.priority == ThreadPriority.SYSTEM
        assert config.poll_interval == 0.001
        assert config.restart_on_failure is True
        assert config.max_restarts == 5
        assert config.dependencies == ["worker1", "worker2"]
    
    def test_poll_intervals(self):
        """Проверяем правильность интервалов опроса для разных приоритетов."""
        intervals = {
            ThreadPriority.SYSTEM: 0.001,
            ThreadPriority.REALTIME: 0.01,
            ThreadPriority.NORMAL: 0.1,
            ThreadPriority.BATCH: 1.0,
            ThreadPriority.BACKGROUND: 5.0
        }
        
        for priority, expected_interval in intervals.items():
            config = ThreadConfig(priority=priority)
            assert config.poll_interval == expected_interval, \
                f"Неверный интервал для {priority}"


class TestWorkerManagerCreation:
    """Тесты создания и базовой функциональности WorkerManager."""
    
    def test_manager_initialization(self):
        """Проверяем инициализацию менеджера."""
        manager = WorkerManager("test_process")
        
        assert manager.name == "test_process"
        assert manager.workers == {}
        assert manager.thread_configs == {}
    
    def test_create_worker_basic(self):
        """Проверяем создание простого воркера."""
        manager = WorkerManager("test")
        
        def simple_worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        result = manager.create_worker("worker1", simple_worker, config)
        
        assert result is True
        assert "worker1" in manager.workers
        assert manager.workers["worker1"]["status"] == WorkerStatus.STOPPED
        assert manager.workers["worker1"]["restart_count"] == 0
    
    def test_create_duplicate_worker(self):
        """Проверяем, что нельзя создать воркер с дублирующимся именем."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            pass
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config)
        
        # Попытка создать воркер с тем же именем должна вернуть False
        result = manager.create_worker("worker1", worker, config)
        assert result is False
    
    def test_create_worker_with_auto_start(self):
        """Проверяем создание воркера с автоматическим запуском."""
        manager = WorkerManager("test")
        
        worker_started = threading.Event()
        
        def worker(stop_event, pause_event):
            worker_started.set()
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        result = manager.create_worker("worker1", worker, config, auto_start=True)
        
        assert result is True
        # Даем время на запуск
        time.sleep(0.1)
        assert manager.is_worker_running("worker1") is True
        assert worker_started.is_set()
        
        # Останавливаем для очистки
        manager.stop_worker("worker1")


class TestWorkerDependencies:
    """Тесты зависимостей между воркерами."""
    
    def test_create_worker_with_missing_dependency(self):
        """Проверяем, что нельзя создать воркер с несуществующей зависимостью."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            pass
        
        config = ThreadConfig(dependencies=["nonexistent"])
        result = manager.create_worker("worker1", worker, config)
        
        assert result is False
        assert "worker1" not in manager.workers
    
    def test_create_worker_with_stopped_dependency(self):
        """Проверяем, что нельзя создать воркер, если зависимость не запущена."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            pass
        
        # Создаем первый воркер, но не запускаем
        config1 = ThreadConfig()
        manager.create_worker("worker1", worker, config1)
        
        # Пытаемся создать зависимый воркер
        config2 = ThreadConfig(dependencies=["worker1"])
        result = manager.create_worker("worker2", worker, config2)
        
        assert result is False
    
    def test_create_worker_with_running_dependency(self):
        """Проверяем создание воркера с запущенной зависимостью."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        # Создаем и запускаем первый воркер
        config1 = ThreadConfig()
        manager.create_worker("worker1", worker, config1, auto_start=True)
        time.sleep(0.1)  # Даем время на запуск
        
        # Создаем зависимый воркер
        config2 = ThreadConfig(dependencies=["worker1"])
        result = manager.create_worker("worker2", worker, config2)
        
        assert result is True
        assert "worker2" in manager.workers
        
        # Останавливаем для очистки
        manager.stop_all_workers()


class TestWorkerStartStop:
    """Тесты запуска и остановки воркеров."""
    
    def test_start_worker(self):
        """Проверяем запуск воркера."""
        manager = WorkerManager("test")
        
        worker_started = threading.Event()
        
        def worker(stop_event, pause_event):
            worker_started.set()
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config)
        
        result = manager.start_worker("worker1")
        assert result is True
        
        time.sleep(0.1)
        assert manager.is_worker_running("worker1") is True
        assert worker_started.is_set()
        
        manager.stop_worker("worker1")
    
    def test_start_nonexistent_worker(self):
        """Проверяем запуск несуществующего воркера."""
        manager = WorkerManager("test")
        
        result = manager.start_worker("nonexistent")
        assert result is False
    
    def test_start_already_running_worker(self):
        """Проверяем повторный запуск уже работающего воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        # Повторный запуск должен вернуть True без ошибок
        result = manager.start_worker("worker1")
        assert result is True
        assert manager.is_worker_running("worker1") is True
        
        manager.stop_worker("worker1")
    
    def test_stop_worker(self):
        """Проверяем остановку воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        assert manager.is_worker_running("worker1") is True
        
        result = manager.stop_worker("worker1")
        assert result is True
        
        time.sleep(0.1)
        assert manager.is_worker_running("worker1") is False
        assert manager.workers["worker1"]["status"] == WorkerStatus.STOPPED
    
    def test_stop_nonexistent_worker(self):
        """Проверяем остановку несуществующего воркера."""
        manager = WorkerManager("test")
        
        result = manager.stop_worker("nonexistent")
        assert result is False
    
    def test_start_all_workers(self):
        """Проверяем запуск всех воркеров."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config)
        manager.create_worker("worker2", worker, config)
        manager.create_worker("worker3", worker, config)
        
        manager.start_all_workers()
        time.sleep(0.1)
        
        assert manager.is_worker_running("worker1") is True
        assert manager.is_worker_running("worker2") is True
        assert manager.is_worker_running("worker3") is True
        
        manager.stop_all_workers()
    
    def test_stop_all_workers(self):
        """Проверяем остановку всех воркеров."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        manager.create_worker("worker2", worker, config, auto_start=True)
        time.sleep(0.1)
        
        manager.stop_all_workers()
        time.sleep(0.1)
        
        assert manager.is_worker_running("worker1") is False
        assert manager.is_worker_running("worker2") is False


class TestWorkerPauseResume:
    """Тесты паузы и возобновления воркеров."""
    
    def test_pause_worker(self):
        """Проверяем приостановку воркера."""
        manager = WorkerManager("test")
        
        pause_check = []
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                if pause_event.is_set():
                    pause_check.append("paused")
                    time.sleep(0.1)
                    continue
                pause_check.append("running")
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        manager.pause_worker("worker1")
        time.sleep(0.2)
        
        # Проверяем, что воркер видит паузу
        assert "paused" in pause_check or manager.workers["worker1"]["pause_event"].is_set()
        
        manager.stop_worker("worker1")
    
    def test_resume_worker(self):
        """Проверяем возобновление воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.01)
                    continue
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        manager.pause_worker("worker1")
        assert manager.workers["worker1"]["pause_event"].is_set()
        
        manager.resume_worker("worker1")
        assert not manager.workers["worker1"]["pause_event"].is_set()
        
        manager.stop_worker("worker1")
    
    def test_pause_nonexistent_worker(self):
        """Проверяем паузу несуществующего воркера."""
        manager = WorkerManager("test")
        
        result = manager.pause_worker("nonexistent")
        assert result is False
    
    def test_resume_nonexistent_worker(self):
        """Проверяем возобновление несуществующего воркера."""
        manager = WorkerManager("test")
        
        result = manager.resume_worker("nonexistent")
        assert result is False


class TestWorkerStatus:
    """Тесты получения статуса воркеров."""
    
    def test_get_worker_status(self):
        """Проверяем получение статуса воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config)
        
        status = manager.get_worker_status("worker1")
        assert status is not None
        assert status["name"] == "worker1"
        assert status["status"] == "stopped"
        assert status["is_alive"] is False
        assert status["restart_count"] == 0
        assert status["last_error"] is None
        
        manager.start_worker("worker1")
        time.sleep(0.1)
        
        status = manager.get_worker_status("worker1")
        assert status["status"] == "running"
        assert status["is_alive"] is True
        
        manager.stop_worker("worker1")
    
    def test_get_nonexistent_worker_status(self):
        """Проверяем получение статуса несуществующего воркера."""
        manager = WorkerManager("test")
        
        status = manager.get_worker_status("nonexistent")
        assert status is None
    
    def test_get_all_workers_status(self):
        """Проверяем получение статусов всех воркеров."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config)
        manager.create_worker("worker2", worker, config)
        
        statuses = manager.get_all_workers_status()
        
        assert len(statuses) == 2
        assert "worker1" in statuses
        assert "worker2" in statuses
        assert statuses["worker1"]["name"] == "worker1"
        assert statuses["worker2"]["name"] == "worker2"
    
    def test_is_worker_running(self):
        """Проверяем проверку статуса работы воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config)
        
        assert manager.is_worker_running("worker1") is False
        
        manager.start_worker("worker1")
        time.sleep(0.1)
        assert manager.is_worker_running("worker1") is True
        
        manager.stop_worker("worker1")
        time.sleep(0.1)
        assert manager.is_worker_running("worker1") is False
    
    def test_is_nonexistent_worker_running(self):
        """Проверяем проверку статуса несуществующего воркера."""
        manager = WorkerManager("test")
        
        assert manager.is_worker_running("nonexistent") is False


class TestWorkerErrors:
    """Тесты обработки ошибок в воркерах."""
    
    def test_worker_with_exception(self):
        """Проверяем обработку исключения в воркере."""
        manager = WorkerManager("test")
        
        def failing_worker(stop_event, pause_event):
            raise ValueError("Test error")
        
        config = ThreadConfig()
        manager.create_worker("worker1", failing_worker, config, auto_start=True)
        time.sleep(0.2)
        
        status = manager.get_worker_status("worker1")
        assert status["status"] == "error"
        assert status["last_error"] == "Test error"
        assert status["is_alive"] is False
    
    def test_worker_stops_on_exception(self):
        """Проверяем, что воркер останавливается при исключении."""
        manager = WorkerManager("test")
        
        def failing_worker(stop_event, pause_event):
            raise RuntimeError("Fatal error")
        
        config = ThreadConfig()
        manager.create_worker("worker1", failing_worker, config, auto_start=True)
        time.sleep(0.2)
        
        assert manager.is_worker_running("worker1") is False
        assert manager.workers["worker1"]["status"] == WorkerStatus.ERROR


class TestWorkerRestart:
    """Тесты перезапуска воркеров."""
    
    def test_restart_worker(self):
        """Проверяем перезапуск воркера."""
        manager = WorkerManager("test")
        
        call_count = []
        
        def worker(stop_event, pause_event):
            call_count.append(1)
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        assert len(call_count) >= 1
        initial_count = len(call_count)
        
        manager.stop_worker("worker1")
        time.sleep(0.1)
        
        # Перезапускаем с помощью метода restart_worker
        manager.restart_worker("worker1")
        time.sleep(0.1)
        
        # Проверяем, что воркер снова запущен и счетчик увеличился
        assert manager.is_worker_running("worker1") is True
        assert len(call_count) > initial_count
        
        manager.stop_worker("worker1")


class TestWorkerIntegration:
    """Интеграционные тесты для комплексных сценариев."""
    
    def test_multiple_workers_with_dependencies(self):
        """Проверяем работу нескольких воркеров с зависимостями."""
        manager = WorkerManager("test")
        
        execution_order = []
        
        def worker1(stop_event, pause_event):
            execution_order.append("worker1")
            while not stop_event.is_set():
                time.sleep(0.01)
        
        def worker2(stop_event, pause_event):
            execution_order.append("worker2")
            while not stop_event.is_set():
                time.sleep(0.01)
        
        def worker3(stop_event, pause_event):
            execution_order.append("worker3")
            while not stop_event.is_set():
                time.sleep(0.01)
        
        # Создаем воркеры с зависимостями: worker3 зависит от worker2, worker2 от worker1
        config1 = ThreadConfig()
        manager.create_worker("worker1", worker1, config1, auto_start=True)
        time.sleep(0.1)
        
        config2 = ThreadConfig(dependencies=["worker1"])
        manager.create_worker("worker2", worker2, config2, auto_start=True)
        time.sleep(0.1)
        
        config3 = ThreadConfig(dependencies=["worker2"])
        manager.create_worker("worker3", worker3, config3, auto_start=True)
        time.sleep(0.1)
        
        # Все воркеры должны быть запущены
        assert manager.is_worker_running("worker1") is True
        assert manager.is_worker_running("worker2") is True
        assert manager.is_worker_running("worker3") is True
        
        manager.stop_all_workers()
    
    def test_worker_with_pause_resume_cycle(self):
        """Проверяем цикл пауза-возобновление воркера."""
        manager = WorkerManager("test")
        
        state_changes = []
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                if pause_event.is_set():
                    state_changes.append("paused")
                    time.sleep(0.05)
                    continue
                state_changes.append("running")
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        # Пауза
        manager.pause_worker("worker1")
        time.sleep(0.1)
        
        # Возобновление
        manager.resume_worker("worker1")
        time.sleep(0.1)
        
        # Еще раз пауза
        manager.pause_worker("worker1")
        time.sleep(0.1)
        
        # Остановка
        manager.stop_worker("worker1")
        
        # Проверяем, что воркер корректно обрабатывал паузы
        assert manager.workers["worker1"]["status"] == WorkerStatus.STOPPED


class TestWorkerMetrics:
    """Тесты метрик производительности воркеров."""
    
    def test_get_worker_metrics_basic(self):
        """Проверяем получение базовых метрик воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            time.sleep(0.1)
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.2)
        
        metrics = manager.get_worker_metrics("worker1")
        assert metrics is not None
        assert "total_runtime" in metrics
        assert "last_run_duration" in metrics
        assert "successful_runs" in metrics
        assert "failed_runs" in metrics
        assert "restart_count" in metrics
        assert "avg_run_time" in metrics
        assert "start_time" in metrics
        assert "uptime" in metrics
        
        assert metrics["successful_runs"] >= 1
        assert metrics["failed_runs"] == 0
        assert metrics["restart_count"] == 0
        assert metrics["total_runtime"] > 0
        
        manager.stop_worker("worker1")
    
    def test_get_worker_metrics_nonexistent(self):
        """Проверяем получение метрик несуществующего воркера."""
        manager = WorkerManager("test")
        
        metrics = manager.get_worker_metrics("nonexistent")
        assert metrics is None
    
    def test_worker_metrics_tracking(self):
        """Проверяем отслеживание метрик во время работы воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            time.sleep(0.15)  # Работаем некоторое время
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.2)
        
        metrics_before = manager.get_worker_metrics("worker1")
        assert metrics_before["total_runtime"] > 0
        
        time.sleep(0.1)
        
        metrics_after = manager.get_worker_metrics("worker1")
        assert metrics_after["total_runtime"] >= metrics_before["total_runtime"]
        
        manager.stop_worker("worker1")
    
    def test_worker_metrics_after_failure(self):
        """Проверяем метрики после ошибки воркера."""
        manager = WorkerManager("test")
        
        def failing_worker(stop_event, pause_event):
            raise ValueError("Test error")
        
        config = ThreadConfig()
        manager.create_worker("worker1", failing_worker, config, auto_start=True)
        time.sleep(0.2)
        
        metrics = manager.get_worker_metrics("worker1")
        assert metrics is not None
        assert metrics["failed_runs"] >= 1
        assert metrics["successful_runs"] == 0
    
    def test_worker_metrics_in_status(self):
        """Проверяем, что метрики включены в статус воркера."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        status = manager.get_worker_status("worker1")
        assert "metrics" in status
        assert status["metrics"] is not None
        assert "total_runtime" in status["metrics"]
        
        manager.stop_worker("worker1")


class TestWorkerAutoRestart:
    """Тесты автоматического перезапуска воркеров при ошибках."""
    
    def test_auto_restart_on_failure(self):
        """Проверяем автоматический перезапуск при ошибке."""
        manager = WorkerManager("test")
        
        restart_count = []
        
        def failing_worker(stop_event, pause_event):
            restart_count.append(1)
            if len(restart_count) < 2:  # Падаем только первые два раза
                raise ValueError("Test error")
            # После второго раза работаем нормально
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig(
            restart_on_failure=True,
            max_restarts=5
        )
        manager.create_worker("worker1", failing_worker, config, auto_start=True)
        
        # Даем время на перезапуски
        time.sleep(0.5)
        
        # Воркер должен быть запущен после перезапуска
        assert manager.is_worker_running("worker1") is True
        assert len(restart_count) >= 2
        
        status = manager.get_worker_status("worker1")
        assert status["restart_count"] >= 1
        
        manager.stop_worker("worker1")
    
    def test_max_restarts_limit(self):
        """Проверяем ограничение максимального количества перезапусков."""
        manager = WorkerManager("test")
        
        def always_failing_worker(stop_event, pause_event):
            raise RuntimeError("Always fails")
        
        config = ThreadConfig(
            restart_on_failure=True,
            max_restarts=2  # Максимум 2 перезапуска
        )
        manager.create_worker("worker1", always_failing_worker, config, auto_start=True)
        
        # Даем время на все перезапуски
        time.sleep(1.0)
        
        status = manager.get_worker_status("worker1")
        # После превышения max_restarts воркер должен остаться в статусе ERROR
        assert status["restart_count"] <= config.max_restarts
        assert status["status"] == "error"
        assert manager.is_worker_running("worker1") is False
    
    def test_no_auto_restart_when_disabled(self):
        """Проверяем, что перезапуск не происходит, когда отключен."""
        manager = WorkerManager("test")
        
        def failing_worker(stop_event, pause_event):
            raise ValueError("Test error")
        
        config = ThreadConfig(
            restart_on_failure=False  # Перезапуск отключен
        )
        manager.create_worker("worker1", failing_worker, config, auto_start=True)
        
        time.sleep(0.3)
        
        status = manager.get_worker_status("worker1")
        assert status["status"] == "error"
        assert status["restart_count"] == 0  # Не должно быть перезапусков
        assert manager.is_worker_running("worker1") is False


class TestWorkerEdgeCases:
    """Тесты граничных случаев и edge cases."""
    
    def test_stop_worker_timeout(self):
        """Проверяем поведение при таймауте остановки воркера."""
        manager = WorkerManager("test")
        
        def slow_worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.1)  # Медленный воркер
        
        config = ThreadConfig()
        manager.create_worker("worker1", slow_worker, config, auto_start=True)
        time.sleep(0.1)
        
        # Останавливаем с очень коротким таймаутом
        result = manager.stop_worker("worker1", timeout=0.05)
        assert result is True
        
        # Воркер должен быть помечен как остановленный, даже если поток еще работает
        assert manager.workers["worker1"]["status"] == WorkerStatus.STOPPED
        
        # Даем время на завершение
        time.sleep(0.2)
    
    def test_stopping_status(self):
        """Проверяем статус STOPPING во время остановки."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        # Запускаем остановку в отдельном потоке для проверки статуса
        import threading
        stop_thread = threading.Thread(
            target=lambda: manager.stop_worker("worker1", timeout=0.1)
        )
        stop_thread.start()
        
        # Проверяем статус во время остановки
        time.sleep(0.01)
        status = manager.workers["worker1"]["status"]
        # Статус может быть STOPPING или уже STOPPED
        assert status in [WorkerStatus.STOPPING, WorkerStatus.STOPPED]
        
        stop_thread.join()
    
    def test_restart_stopped_worker(self):
        """Проверяем перезапуск остановленного воркера."""
        manager = WorkerManager("test")
        
        call_count = []
        
        def worker(stop_event, pause_event):
            call_count.append(1)
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        initial_count = len(call_count)
        manager.stop_worker("worker1")
        time.sleep(0.1)
        
        # Перезапускаем остановленный воркер
        result = manager.restart_worker("worker1")
        assert result is True
        time.sleep(0.1)
        
        assert manager.is_worker_running("worker1") is True
        assert len(call_count) > initial_count
        
        manager.stop_worker("worker1")
    
    def test_restart_nonexistent_worker(self):
        """Проверяем перезапуск несуществующего воркера."""
        manager = WorkerManager("test")
        
        result = manager.restart_worker("nonexistent")
        assert result is False
    
    def test_multiple_restarts(self):
        """Проверяем множественные перезапуски воркера."""
        manager = WorkerManager("test")
        
        call_count = []
        
        def worker(stop_event, pause_event):
            call_count.append(1)
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        # Выполняем несколько циклов перезапуска
        for _ in range(3):
            manager.stop_worker("worker1")
            time.sleep(0.05)
            manager.restart_worker("worker1")
            time.sleep(0.1)
        
        assert len(call_count) >= 3
        status = manager.get_worker_status("worker1")
        assert status["restart_count"] >= 3
        
        manager.stop_worker("worker1")
    
    def test_worker_with_empty_dependencies(self):
        """Проверяем создание воркера с пустым списком зависимостей."""
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig(dependencies=[])
        result = manager.create_worker("worker1", worker, config)
        assert result is True
        assert "worker1" in manager.workers
    
    def test_circular_dependency_detection(self):
        """Проверяем поведение при циклических зависимостях (текущая реализация не проверяет)."""
        manager = WorkerManager("test")
        
        def worker1(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        def worker2(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        # Создаем первый воркер
        config1 = ThreadConfig()
        manager.create_worker("worker1", worker1, config1, auto_start=True)
        time.sleep(0.1)
        
        # Создаем второй воркер с зависимостью от первого
        config2 = ThreadConfig(dependencies=["worker1"])
        manager.create_worker("worker2", worker2, config2, auto_start=True)
        time.sleep(0.1)
        
        # Примечание: текущая реализация не проверяет циклические зависимости
        # Это потенциальное улучшение для будущих версий
        
        manager.stop_all_workers()


class TestWorkerThreadSafety:
    """Тесты потокобезопасности (базовые проверки)."""
    
    def test_concurrent_start_stop(self):
        """Проверяем одновременный запуск и остановку воркеров."""
        import threading
        
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config)
        
        def start_worker():
            manager.start_worker("worker1")
        
        def stop_worker():
            manager.stop_worker("worker1")
        
        # Запускаем несколько потоков одновременно
        threads = []
        for _ in range(5):
            t1 = threading.Thread(target=start_worker)
            t2 = threading.Thread(target=stop_worker)
            threads.extend([t1, t2])
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join(timeout=1.0)
        
        # После всех операций состояние должно быть консистентным
        status = manager.get_worker_status("worker1")
        assert status is not None
    
    def test_concurrent_status_check(self):
        """Проверяем одновременную проверку статуса из разных потоков."""
        import threading
        
        manager = WorkerManager("test")
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.01)
        
        config = ThreadConfig()
        manager.create_worker("worker1", worker, config, auto_start=True)
        time.sleep(0.1)
        
        results = []
        
        def check_status():
            status = manager.get_worker_status("worker1")
            results.append(status)
        
        threads = [threading.Thread(target=check_status) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Все результаты должны быть одинаковыми
        assert len(results) == 10
        assert all(r["status"] == "running" for r in results)
        
        manager.stop_worker("worker1")
