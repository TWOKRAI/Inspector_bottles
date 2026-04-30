"""
Тесты сценариев использования фреймворка.

Этот модуль содержит тесты типичных сценариев использования фреймворка
в реальных приложениях. Эти тесты демонстрируют best practices и
показывают как правильно использовать фреймворк.

Проверяемые сценарии:
- Создание процесса с воркерами - базовый сценарий использования
- Отправка сообщений между процессами - межпроцессная коммуникация
- Работа с конфигурациями - управление настройками
- Обработка ошибок и восстановление - надежность системы
- Graceful shutdown - корректное завершение работы

Использование:
    pytest src/multiprocess_framework/tests/integration/test_usage_scenarios.py -v

Документация:
    См. INTEGRATION_TESTS_GUIDE.md для подробного руководства
"""

import pytest
import time
from multiprocessing import Event

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import WorkerManager, ThreadConfig, ThreadPriority


class TestCreateProcessWithWorkers:
    """
    Тест создания процесса с воркерами.
    
    Демонстрирует базовый сценарий использования фреймворка:
    создание процесса и добавление воркеров для обработки задач.
    """
    
    def test_create_process_and_workers(self):
        """
        Тест: Создание процесса и добавление воркеров.
        
        Демонстрирует:
        - Создание ProcessModule
        - Создание воркеров через WorkerManager
        - Запуск воркеров
        - Проверку работы воркеров
        
        Это базовый сценарий для большинства приложений на фреймворке.
        """
        # Вход: Создаем SharedResourcesManager
        shared_resources = SharedResourcesManager()
        shared_resources.initialize()
        
        # Действие: Создаем процесс
        process = ProcessModule(
            name="test_process",
            shared_resources=shared_resources
        )
        process.initialize()
        
        # Действие: Создаем воркеров
        worker_results = []
        
        def worker_func(stop_event, pause_event):
            worker_results.append("worker_started")
            while not stop_event.is_set():
                time.sleep(0.1)
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        result = process.worker_manager.create_worker("worker1", worker_func, config, auto_start=True)
        
        # Проверка: Процесс создан, воркер создан и запущен
        assert result is True
        assert process.worker_manager.has_worker("worker1")
        assert process.worker_manager.is_worker_running("worker1")
        
        # Даем время воркеру запуститься
        time.sleep(0.2)
        assert len(worker_results) > 0
        
        # Выход: Останавливаем процесс
        process.worker_manager.stop_all_workers()
        process.shutdown()
        shared_resources.shutdown()


class TestInterProcessCommunication:
    """Тест межпроцессного взаимодействия."""
    
    def test_send_message_between_processes(self):
        """Тест отправки сообщений между процессами."""
        # TODO: Реализовать после исправления тестов RouterModule и MessageModule
        # Вход: Два процесса
        # Действие: Отправка сообщения от одного процесса другому
        # Проверка: Сообщение получено
        pass


class TestConfigurationManagement:
    """Тест работы с конфигурациями."""
    
    def test_load_and_use_config(self):
        """Тест загрузки и использования конфигурации."""
        # TODO: Реализовать после исправления тестов ConfigModule
        # Вход: Конфигурационный файл
        # Действие: Загрузка конфигурации
        # Проверка: Конфигурация доступна в процессе
        pass


class TestErrorHandlingAndRecovery:
    """
    Тест обработки ошибок и восстановления.
    
    Проверяет способность системы восстанавливаться после ошибок.
    Это критически важно для надежных приложений.
    """
    
    def test_worker_restart_on_failure(self):
        """
        Тест: Автоматический перезапуск воркера при ошибке.
        
        Проверяет:
        - Обработку ошибок в воркерах
        - Автоматический перезапуск воркера при сбое
        - Корректную работу после перезапуска
        
        Использует ThreadConfig с параметрами:
        - restart_on_failure=True - включить автоперезапуск
        - max_restarts=3 - максимальное количество перезапусков
        """
        shared_resources = SharedResourcesManager()
        shared_resources.initialize()
        
        process = ProcessModule(
            name="test_process",
            shared_resources=shared_resources
        )
        process.initialize()
        
        # Создаем воркера который падает один раз
        call_count = [0]
        
        def failing_worker(stop_event, pause_event):
            call_count[0] += 1
            if call_count[0] < 2:
                raise RuntimeError("Test error")
            while not stop_event.is_set():
                time.sleep(0.1)
        
        config = ThreadConfig(
            priority=ThreadPriority.NORMAL,
            restart_on_failure=True,
            max_restarts=3
        )
        
        process.worker_manager.create_worker("failing_worker", failing_worker, config, auto_start=True)
        
        # Даем время на перезапуск
        time.sleep(0.5)
        
        # Проверка: Воркер перезапустился и работает
        assert call_count[0] >= 2
        assert process.worker_manager.is_worker_running("failing_worker")
        
        # Очистка
        process.worker_manager.stop_all_workers()
        process.shutdown()
        shared_resources.shutdown()


class TestGracefulShutdown:
    """
    Тест корректного завершения работы.
    
    Проверяет graceful shutdown - корректное завершение работы всех
    компонентов без потери данных и утечек ресурсов.
    """
    
    def test_graceful_shutdown(self):
        """
        Тест: Корректное завершение процесса и воркеров.
        
        Проверяет:
        - Корректную остановку всех воркеров
        - Завершение процесса без ошибок
        - Отсутствие "висящих" потоков после shutdown
        
        Важно: Все ресурсы должны быть освобождены после shutdown.
        """
        shared_resources = SharedResourcesManager()
        shared_resources.initialize()
        
        process = ProcessModule(
            name="test_process",
            shared_resources=shared_resources
        )
        process.initialize()
        
        # Создаем воркеров
        def worker_func(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.1)
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        process.worker_manager.create_worker("worker1", worker_func, config, auto_start=True)
        process.worker_manager.create_worker("worker2", worker_func, config, auto_start=True)
        
        time.sleep(0.1)
        
        # Проверка: Воркеры запущены
        assert process.worker_manager.is_worker_running("worker1")
        assert process.worker_manager.is_worker_running("worker2")
        
        # Действие: Корректное завершение
        process.shutdown()
        
        # Проверка: Воркеры остановлены, процесс завершен
        assert not process.worker_manager.is_worker_running("worker1")
        assert not process.worker_manager.is_worker_running("worker2")
        assert not process.is_initialized
        
        shared_resources.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

