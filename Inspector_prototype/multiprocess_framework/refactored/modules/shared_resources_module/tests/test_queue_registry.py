"""
Юнит-тесты для QueueRegistry.
"""

import pytest
from multiprocessing import Queue

from ..queues.queue_registry import QueueRegistry


class TestQueueRegistry:
    """Тесты для QueueRegistry."""
    
    def test_initialization(self):
        """Тест инициализации реестра."""
        registry = QueueRegistry()
        assert registry is not None
        assert registry.manager_name == "QueueRegistry"
    
    def test_initialize(self):
        """Тест инициализации."""
        registry = QueueRegistry()
        assert registry.initialize() is True
        assert registry.is_initialized is True
    
    def test_create_queues(self):
        """Тест создания очередей."""
        registry = QueueRegistry()
        
        queue_config = {
            "system": {"maxsize": 100},
            "data": {"maxsize": 50}
        }
        
        queues = registry.create_queues(queue_config)
        assert len(queues) == 2
        assert "system" in queues
        assert "data" in queues
        # Проверяем что это очереди (используем hasattr вместо isinstance для совместимости)
        assert hasattr(queues["system"], 'put')
        assert hasattr(queues["system"], 'get')
        assert hasattr(queues["data"], 'put')
        assert hasattr(queues["data"], 'get')
    
    def test_register_process_queues(self):
        """Тест регистрации очередей процесса."""
        registry = QueueRegistry()
        registry.initialize()
        
        queues = {
            "system": Queue(),
            "data": Queue()
        }
        
        result = registry.register_process_queues("test_process", queues)
        assert result is True
        
        assert "test_process" in registry.registered_queues
        assert len(registry.registered_queues) == 1
    
    def test_get_queue(self):
        """Тест получения очереди."""
        registry = QueueRegistry()
        registry.initialize()
        
        queue = Queue()
        registry.register_process_queues("test_process", {"system": queue})
        
        retrieved_queue = registry.get_queue("test_process", "system")
        assert retrieved_queue is not None
        assert retrieved_queue == queue
        
        assert registry.get_queue("test_process", "nonexistent") is None
        assert registry.get_queue("nonexistent", "system") is None
    
    def test_send_receive_message(self):
        """Тест отправки и получения сообщений."""
        registry = QueueRegistry()
        registry.initialize()
        
        queue = Queue()
        registry.register_process_queues("test_process", {"system": queue})
        
        message = {"type": "test", "data": "hello"}
        assert registry.send_to_queue("test_process", "system", message) is True
        
        # Небольшая задержка для синхронизации (на Windows может быть нужно)
        import time
        time.sleep(0.01)
        
        received = registry.receive_from_queue("test_process", "system")
        assert received == message
    
    def test_broadcast_message(self):
        """Тест рассылки сообщений."""
        registry = QueueRegistry()
        registry.initialize()
        
        registry.register_process_queues("process1", {"system": Queue()})
        registry.register_process_queues("process2", {"system": Queue()})
        
        message = {"type": "broadcast"}
        sent_count = registry.broadcast_message(message, "system")
        assert sent_count == 2
    
    def test_clear_queue(self):
        """Тест очистки очереди."""
        registry = QueueRegistry()
        registry.initialize()
        
        queue = Queue()
        queue.put("item1")
        queue.put("item2")
        
        # В Windows queue.empty() может быть ненадежным, поэтому используем другой подход
        # Сначала проверяем что в очереди 2 элемента
        initial_size = queue.qsize()
        assert initial_size == 2, f"Expected 2 items, got {initial_size}"
        
        registry.clear_queue(queue, keep_elements=1)
        
        # Должен остаться один элемент (последний)
        # В Windows может быть задержка, поэтому проверяем с небольшим допуском
        final_size = queue.qsize()
        assert final_size == 1, f"Expected 1 item after clearing, got {final_size}"
        
        # Проверяем что остался последний элемент
        remaining_item = queue.get()
        assert remaining_item == "item2", f"Expected 'item2', got {remaining_item}"
    
    def test_get_queue_sizes(self):
        """Тест получения размеров очередей."""
        registry = QueueRegistry()
        registry.initialize()
        
        queue1 = Queue()
        queue1.put("item1")
        queue2 = Queue()
        
        registry.register_process_queues("process1", {"system": queue1, "data": queue2})
        
        sizes = registry.get_queue_sizes()
        assert "process1" in sizes
        assert sizes["process1"]["system"] >= 1
        assert sizes["process1"]["data"] == 0

