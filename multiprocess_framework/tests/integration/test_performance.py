"""
Тесты производительности фреймворка.

Этот модуль содержит тесты производительности различных компонентов фреймворка.
Тесты проверяют скорость работы и выявляют узкие места в производительности.

Проверяемые аспекты производительности:
- Межпроцессная коммуникация - скорость передачи сообщений
- Работа с очередями - пропускная способность очередей
- Работа с памятью - скорость выделения и освобождения памяти
- Работа с конфигурациями - скорость доступа к конфигурациям
- Создание воркеров - скорость создания потоков

Использование:
    pytest src/multiprocess_framework/tests/integration/test_performance.py -v -s

Примечание: Используйте флаг -s для вывода метрик производительности.

Документация:
    См. INTEGRATION_TESTS_GUIDE.md для подробного руководства
"""

import pytest
import time
from multiprocessing import Queue

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager


class TestInterProcessCommunicationPerformance:
    """
    Тесты производительности межпроцессной коммуникации.
    
    Проверяет скорость передачи данных между процессами через очереди.
    Эти тесты помогают выявить узкие места в межпроцессной коммуникации.
    """
    
    def test_queue_performance(self):
        """
        Тест: Производительность работы с очередями.
        
        Проверяет:
        - Скорость отправки сообщений в очередь
        - Скорость получения сообщений из очереди
        - Пропускную способность очереди (сообщений в секунду)
        
        Метрики:
        - Отправка 1000 сообщений должна занимать < 1 секунды
        - Получение 1000 сообщений должно занимать < 1 секунды
        
        Выводит метрики производительности в консоль.
        """
        # Вход: Создаем очередь
        queue = Queue(maxsize=1000)
        
        # Действие: Отправляем сообщения
        message_count = 1000
        start_time = time.time()
        
        for i in range(message_count):
            queue.put({"id": i, "data": f"message_{i}"})
        
        send_time = time.time() - start_time
        
        # Действие: Получаем сообщения
        start_time = time.time()
        
        received_count = 0
        while received_count < message_count:
            try:
                queue.get(timeout=0.1)
                received_count += 1
            except:
                break
        
        receive_time = time.time() - start_time
        
        # Проверка: Производительность приемлема
        assert received_count == message_count
        assert send_time < 1.0  # Отправка 1000 сообщений за <1 секунду
        assert receive_time < 1.0  # Получение 1000 сообщений за <1 секунду
        
        # Вывод метрик
        print(f"\nПроизводительность очереди:")
        print(f"  Отправка {message_count} сообщений: {send_time:.3f}s ({message_count/send_time:.0f} msg/s)")
        print(f"  Получение {message_count} сообщений: {receive_time:.3f}s ({message_count/receive_time:.0f} msg/s)")


class TestMemoryPerformance:
    """Тесты производительности работы с памятью."""
    
    def test_memory_allocation_performance(self):
        """Тест производительности выделения памяти."""
        # TODO: Реализовать после исправления тестов MemoryManager
        # Вход: MemoryManager
        # Действие: Выделение памяти для изображений
        # Проверка: Производительность приемлема
        pass


class TestConfigurationPerformance:
    """Тесты производительности работы с конфигурациями."""
    
    def test_config_access_performance(self):
        """Тест производительности доступа к конфигурации."""
        # TODO: Реализовать после исправления тестов ConfigModule
        # Вход: ConfigManager с конфигурацией
        # Действие: Множественные обращения к конфигурации
        # Проверка: Производительность приемлема
        pass


class TestWorkerPerformance:
    """
    Тесты производительности воркеров.
    
    Проверяет скорость создания и управления потоками (воркерами).
    Эти тесты важны для приложений, которые создают много воркеров.
    """
    
    def test_worker_creation_performance(self):
        """
        Тест: Производительность создания воркеров.
        
        Проверяет:
        - Скорость создания множества воркеров
        - Время создания одного воркера
        - Пропускную способность создания воркеров
        
        Метрики:
        - Создание 100 воркеров должно занимать < 5 секунд
        
        Выводит метрики производительности в консоль.
        """
        from multiprocess_framework.modules.worker_module import WorkerManager, ThreadConfig, ThreadPriority
        
        manager = WorkerManager("test_manager")
        manager.initialize()
        
        worker_count = 100
        
        def worker_func(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.1)
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        
        # Действие: Создаем множество воркеров
        start_time = time.time()
        
        for i in range(worker_count):
            manager.create_worker(f"worker_{i}", worker_func, config)
        
        creation_time = time.time() - start_time
        
        # Проверка: Производительность приемлема
        assert creation_time < 5.0  # Создание 100 воркеров за <5 секунд
        
        # Вывод метрик
        print(f"\nПроизводительность создания воркеров:")
        print(f"  Создание {worker_count} воркеров: {creation_time:.3f}s ({worker_count/creation_time:.0f} workers/s)")
        
        # Очистка
        manager.stop_all_workers()
        manager.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])  # -s для вывода print

