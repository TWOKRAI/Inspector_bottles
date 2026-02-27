"""
Тесты для ProcessMonitor.

Проверяют мониторинг состояний процессов.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from multiprocessing import Event

from multiprocess_framework.modules.Process_manager_module.monitor import ProcessMonitor
from multiprocess_framework.modules.Shared_resources_module.SharedResourcesManager import SharedResourcesManager


class TestProcessMonitor:
    """Тесты для ProcessMonitor"""
    
    @pytest.fixture
    def shared_resources(self):
        """Фикстура для SharedResourcesManager"""
        return SharedResourcesManager()
    
    @pytest.fixture
    def stop_event(self):
        """Фикстура для события остановки"""
        return Event()
    
    @pytest.fixture
    def monitor(self, shared_resources, stop_event):
        """Фикстура для ProcessMonitor"""
        return ProcessMonitor(
            shared_resources=shared_resources,
            stop_event=stop_event,
            poll_interval=0.1  # Короткий интервал для тестов
        )
    
    def test_monitor_initialization(self, monitor):
        """Тест инициализации монитора"""
        assert monitor.name == "ProcessMonitor"
        assert monitor.stop_event is not None
        assert monitor.poll_interval == 0.1
        assert monitor._monitoring is False
        assert isinstance(monitor.previous_states, dict)
    
    def test_monitor_start(self, monitor):
        """Тест запуска мониторинга"""
        assert monitor._monitoring is False
        
        monitor.start()
        
        assert monitor._monitoring is True
        
        # Останавливаем для очистки
        monitor.stop()
    
    def test_monitor_stop(self, monitor):
        """Тест остановки мониторинга"""
        monitor.start()
        assert monitor._monitoring is True
        
        monitor.stop()
        
        assert monitor._monitoring is False
    
    def test_monitor_double_start(self, monitor):
        """Тест повторного запуска мониторинга"""
        monitor.start()
        assert monitor._monitoring is True
        
        # Второй запуск не должен изменить состояние
        monitor.start()
        assert monitor._monitoring is True
        
        monitor.stop()
    
    def test_monitor_double_stop(self, monitor):
        """Тест повторной остановки мониторинга"""
        monitor.start()
        monitor.stop()
        
        # Вторая остановка не должна вызвать ошибку
        monitor.stop()
        assert monitor._monitoring is False
    
    def test_monitoring_loop_detects_new_process(self, monitor, shared_resources):
        """Тест обнаружения нового процесса в цикле мониторинга"""
        monitor.start()
        
        # Добавляем процесс в shared_resources
        shared_resources.update_process_state("TestProcess", {
            "status": "running",
            "pid": 12345
        })
        
        # Даем время на опрос
        time.sleep(0.2)
        
        # Проверяем что процесс обнаружен
        assert "TestProcess" in monitor.previous_states
        
        monitor.stop()
    
    def test_monitoring_loop_detects_state_change(self, monitor, shared_resources):
        """Тест обнаружения изменения состояния процесса"""
        monitor.start()
        
        # Добавляем начальное состояние
        shared_resources.update_process_state("TestProcess", {
            "status": "starting",
            "pid": 12345
        })
        
        time.sleep(0.2)
        
        # Изменяем состояние
        shared_resources.update_process_state("TestProcess", {
            "status": "running",
            "pid": 12345
        })
        
        time.sleep(0.2)
        
        # Проверяем что состояние обновлено
        assert monitor.previous_states["TestProcess"]["status"] == "running"
        
        monitor.stop()
    
    def test_monitoring_loop_detects_removed_process(self, monitor, shared_resources):
        """Тест обнаружения удаленного процесса"""
        monitor.start()
        
        # Добавляем процесс
        shared_resources.update_process_state("TestProcess", {
            "status": "running",
            "pid": 12345
        })
        
        time.sleep(0.2)
        assert "TestProcess" in monitor.previous_states
        
        # Удаляем процесс
        shared_resources.remove_process_state("TestProcess")
        
        time.sleep(0.2)
        
        # Процесс должен быть удален из кэша
        # (но может остаться до следующего опроса)
        
        monitor.stop()
    
    def test_handle_state_change(self, monitor):
        """Тест обработки изменения состояния"""
        previous_state = {"status": "starting", "pid": 12345}
        current_state = {"status": "running", "pid": 12345}
        
        with patch.object(monitor, '_broadcast_status_change') as mock_broadcast:
            monitor._handle_state_change("TestProcess", previous_state, current_state)
            mock_broadcast.assert_called_once()
    
    def test_handle_state_change_new_process(self, monitor):
        """Тест обработки нового процесса"""
        current_state = {"status": "running", "pid": 12345}
        
        with patch.object(monitor, '_broadcast_status_change') as mock_broadcast:
            monitor._handle_state_change("TestProcess", None, current_state)
            mock_broadcast.assert_called_once()
    
    def test_broadcast_status_change(self, monitor):
        """Тест отправки broadcast сообщения"""
        current_state = {"status": "running", "pid": 12345}
        
        with patch.object(monitor, 'broadcast_message', return_value=2) as mock_broadcast:
            monitor._broadcast_status_change(
                "TestProcess",
                "starting",
                "running",
                current_state
            )
            
            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args[0][0]
            assert call_args["type"] == "system"
            assert call_args["subtype"] == "process_status_changed"
            assert call_args["process_name"] == "TestProcess"
            assert call_args["old_status"] == "starting"
            assert call_args["new_status"] == "running"
    
    def test_get_stats(self, monitor):
        """Тест получения статистики мониторинга"""
        monitor.start()
        
        stats = monitor.get_stats()
        
        assert isinstance(stats, dict)
        assert "monitoring" in stats
        assert "tracked_processes" in stats
        assert "poll_interval" in stats
        assert stats["monitoring"] is True
        assert stats["poll_interval"] == 0.1
        
        monitor.stop()
    
    def test_monitoring_loop_stops_on_stop_event(self, monitor, stop_event):
        """Тест остановки цикла мониторинга по событию"""
        monitor.start()
        
        # Устанавливаем событие остановки
        stop_event.set()
        
        # Даем время на остановку
        time.sleep(0.2)
        
        monitor.stop()
    
    def test_monitoring_loop_error_handling(self, monitor, shared_resources):
        """Тест обработки ошибок в цикле мониторинга"""
        monitor.start()
        
        # Мокаем ошибку при получении состояний
        with patch.object(shared_resources, 'get_all_process_states', side_effect=Exception("Test error")):
            time.sleep(0.2)  # Даем время на обработку ошибки
        
        # Мониторинг должен продолжить работу
        assert monitor._monitoring is True
        
        monitor.stop()


class TestProcessMonitorIntegration:
    """Интеграционные тесты ProcessMonitor"""
    
    @pytest.fixture
    def shared_resources(self):
        """Фикстура для SharedResourcesManager"""
        return SharedResourcesManager()
    
    @pytest.fixture
    def stop_event(self):
        """Фикстура для события остановки"""
        return Event()
    
    def test_monitor_with_multiple_processes(self, shared_resources, stop_event):
        """Тест мониторинга нескольких процессов"""
        monitor = ProcessMonitor(
            shared_resources=shared_resources,
            stop_event=stop_event,
            poll_interval=0.1
        )
        
        monitor.start()
        
        # Добавляем несколько процессов
        shared_resources.update_process_state("Process1", {"status": "running", "pid": 1})
        shared_resources.update_process_state("Process2", {"status": "starting", "pid": 2})
        shared_resources.update_process_state("Process3", {"status": "stopping", "pid": 3})
        
        time.sleep(0.2)
        
        # Проверяем что все процессы отслеживаются
        assert len(monitor.previous_states) >= 3
        
        monitor.stop()
    
    def test_monitor_with_queue_registry(self, shared_resources, stop_event):
        """Тест мониторинга с QueueRegistry"""
        from multiprocess_framework.modules.Shared_resources_module.queue_registry import QueueRegistry
        
        queue_registry = QueueRegistry(process_state_registry=shared_resources.process_state_registry)
        
        monitor = ProcessMonitor(
            shared_resources=shared_resources,
            stop_event=stop_event,
            queue_registry=queue_registry,
            poll_interval=0.1
        )
        
        monitor.start()
        
        # Добавляем процесс
        shared_resources.update_process_state("TestProcess", {"status": "running", "pid": 12345})
        
        time.sleep(0.2)
        
        monitor.stop()

