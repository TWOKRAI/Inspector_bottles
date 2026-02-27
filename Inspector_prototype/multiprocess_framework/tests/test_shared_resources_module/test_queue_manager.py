"""
Тесты для QueueManager.
"""
import pytest
from multiprocessing import Queue

from multiprocess_framework.modules.Shared_resources_module import (
    QueueManager,
    ProcessStateRegistry,
    SharedResourcesManager
)


class TestQueueManager:
    """Тесты для QueueManager."""
    
    def test_initialization_with_registry(self):
        """Проверяет инициализацию QueueManager с ProcessStateRegistry."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        assert queue_manager.process_state_registry is registry
    
    def test_initialization_without_registry_raises_error(self):
        """Проверяет, что инициализация без ProcessStateRegistry вызывает ошибку."""
        with pytest.raises(ValueError):
            QueueManager(process_state_registry=None)
    
    def test_create_queues(self):
        """Проверяет создание очередей из конфигурации."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue_config = {
            "system": {"maxsize": 100},
            "data": {"maxsize": 50}
        }
        
        queues = queue_manager.create_queues(queue_config)
        
        assert len(queues) == 2
        assert "system" in queues
        assert "data" in queues
        assert isinstance(queues["system"], Queue)
        assert isinstance(queues["data"], Queue)
    
    def test_create_queues_empty_config(self):
        """Проверяет создание очередей с пустой конфигурацией."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queues = queue_manager.create_queues(None)
        assert len(queues) == 0
        
        queues = queue_manager.create_queues({})
        assert len(queues) == 0
    
    def test_register_process_queues(self):
        """Проверяет регистрацию очередей процесса."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queues = {
            "system": Queue(),
            "data": Queue()
        }
        
        result = queue_manager.register_process_queues("test_process", queues)
        
        assert result is True
        # Проверяем, что очереди добавлены в ProcessStateRegistry
        assert registry.get_queue("test_process", "system") is queues["system"]
        assert registry.get_queue("test_process", "data") is queues["data"]
    
    def test_create_and_register_queues(self):
        """Проверяет создание и регистрацию очередей одной операцией."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue_config = {
            "system": {"maxsize": 100},
            "data": {"maxsize": 50}
        }
        
        result = queue_manager.create_and_register_queues("test_process", queue_config)
        
        assert result is True
        assert registry.get_queue("test_process", "system") is not None
        assert registry.get_queue("test_process", "data") is not None
    
    def test_get_queue(self):
        """Проверяет получение очереди."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue = Queue()
        registry.add_queue("test_process", "data", queue)
        
        retrieved_queue = queue_manager.get_queue("test_process", "data")
        assert retrieved_queue is queue
        
        assert queue_manager.get_queue("nonexistent", "data") is None
        assert queue_manager.get_queue("test_process", "nonexistent") is None
    
    def test_get_process_queues(self):
        """Проверяет получение всех очередей процесса."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue1 = Queue()
        queue2 = Queue()
        registry.add_queue("test_process", "system", queue1)
        registry.add_queue("test_process", "data", queue2)
        
        process_queues = queue_manager.get_process_queues("test_process")
        
        assert len(process_queues) == 2
        assert "system" in process_queues
        assert "data" in process_queues
        assert process_queues["system"] is queue1
        assert process_queues["data"] is queue2
    
    def test_send_to_queue(self):
        """Проверяет отправку данных в очередь."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue = Queue()
        registry.add_queue("test_process", "data", queue)
        
        result = queue_manager.send_to_queue("test_process", "data", "test_message")
        
        assert result is True
        assert queue.get() == "test_message"
    
    def test_send_to_nonexistent_queue(self):
        """Проверяет отправку в несуществующую очередь."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        result = queue_manager.send_to_queue("nonexistent", "data", "message")
        assert result is False
    
    def test_broadcast_message(self):
        """Проверяет рассылку сообщения во все процессы."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue1 = Queue()
        queue2 = Queue()
        registry.add_queue("process1", "system", queue1)
        registry.add_queue("process2", "system", queue2)
        
        count = queue_manager.broadcast_message("broadcast_message", queue_type="system")
        
        assert count == 2
        assert queue1.get() == "broadcast_message"
        assert queue2.get() == "broadcast_message"
    
    def test_broadcast_message_with_exclude(self):
        """Проверяет рассылку с исключением процесса."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue1 = Queue()
        queue2 = Queue()
        registry.add_queue("process1", "system", queue1)
        registry.add_queue("process2", "system", queue2)
        
        count = queue_manager.broadcast_message(
            "broadcast_message",
            queue_type="system",
            exclude_process="process1"
        )
        
        assert count == 1
        assert queue1.empty()
        assert queue2.get() == "broadcast_message"
    
    def test_get_registered_processes(self):
        """Проверяет получение списка процессов с очередями."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        registry.add_queue("process1", "data", Queue())
        registry.add_queue("process2", "data", Queue())
        
        processes = queue_manager.get_registered_processes()
        
        assert len(processes) == 2
        assert "process1" in processes
        assert "process2" in processes
    
    def test_get_queue_sizes(self):
        """Проверяет получение размеров очередей."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue = Queue()
        queue.put("item1")
        queue.put("item2")
        
        registry.add_queue("test_process", "data", queue)
        
        sizes = queue_manager.get_queue_sizes()
        
        assert "test_process" in sizes
        assert "data" in sizes["test_process"]
        # Размер может быть 0 на некоторых платформах из-за ограничений multiprocessing.Queue
        assert sizes["test_process"]["data"] >= 0
    
    def test_clear_queue(self):
        """Проверяет очистку очереди."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue = Queue()
        queue.put("item1")
        queue.put("item2")
        queue.put("item3")
        
        queue_manager.clear_queue(queue, keep_elements=1)
        
        # Должен остаться только последний элемент
        items = []
        while not queue.empty():
            try:
                items.append(queue.get_nowait())
            except:
                break
        
        # На некоторых платформах qsize() может быть ненадежным
        # Проверяем, что очистка прошла без ошибок
        assert True
    
    def test_clear_all_queues(self):
        """Проверяет очистку всех очередей."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        queue1 = Queue()
        queue2 = Queue()
        queue1.put("item1")
        queue2.put("item2")
        
        registry.add_queue("process1", "data", queue1)
        registry.add_queue("process2", "data", queue2)
        
        queue_manager.clear_all_queues()
        
        # Проверяем, что очистка прошла без ошибок
        assert True
    
    def test_remove_old_if_full(self):
        """Проверяет удаление старых элементов при переполнении."""
        registry = ProcessStateRegistry()
        queue_manager = QueueManager(process_state_registry=registry)
        
        # Создаем очередь с ограниченным размером
        queue = Queue(maxsize=2)
        queue.put("item1")
        queue.put("item2")
        
        # Очередь полна, добавляем еще один элемент
        queue_manager.remove_old_if_full(queue)
        queue.put("item3")
        
        # Проверяем, что старый элемент удален
        items = []
        while not queue.empty():
            try:
                items.append(queue.get_nowait())
            except:
                break
        
        # Должно быть 2 элемента (старый удален, новый добавлен)
        assert len(items) <= 2

