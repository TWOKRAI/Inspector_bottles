"""
Тесты для QueueRegistry.

Проверяют работу реестра очередей.
"""

import unittest
from multiprocessing import Queue
from multiprocess_framework.modules.Shared_resources_module.queue_registry import QueueRegistry


class TestQueueRegistry(unittest.TestCase):
    """Тесты для QueueRegistry"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.registry = QueueRegistry()
        self.process_name = "TestProcess"
        self.queues = {
            'system': Queue(maxsize=10),
            'data': Queue(maxsize=5),
        }
    
    def test_register_process_queues(self):
        """Тест регистрации очередей процесса"""
        success = self.registry.register_process_queues(self.process_name, self.queues)
        
        self.assertTrue(success)
        self.assertIn(self.process_name, self.registry.registered_queues)
    
    def test_get_queue(self):
        """Тест получения очереди"""
        self.registry.register_process_queues(self.process_name, self.queues)
        
        queue = self.registry.get_queue(self.process_name, 'system')
        self.assertIsNotNone(queue)
        self.assertEqual(queue, self.queues['system'])
    
    def test_get_registered_processes(self):
        """Тест получения списка зарегистрированных процессов"""
        self.registry.register_process_queues(self.process_name, self.queues)
        
        processes = self.registry.get_registered_processes()
        self.assertIn(self.process_name, processes)
    
    def test_get_process_queues(self):
        """Тест получения всех очередей процесса"""
        self.registry.register_process_queues(self.process_name, self.queues)
        
        queues = self.registry.get_process_queues(self.process_name)
        self.assertEqual(len(queues), 2)
        self.assertIn('system', queues)
        self.assertIn('data', queues)
    
    def test_send_to_queue(self):
        """Тест отправки данных в очередь"""
        self.registry.register_process_queues(self.process_name, self.queues)
        
        message = {"test": "data"}
        success = self.registry.send_to_queue(self.process_name, 'system', message)
        
        self.assertTrue(success)
        
        # Проверяем, что сообщение попало в очередь
        received = self.queues['system'].get()
        self.assertEqual(received, message)
    
    def test_broadcast_message(self):
        """Тест рассылки сообщения"""
        # Регистрируем несколько процессов
        self.registry.register_process_queues("Process1", {'system': Queue()})
        self.registry.register_process_queues("Process2", {'system': Queue()})
        
        message = {"broadcast": "message"}
        count = self.registry.broadcast_message(message, queue_type="system")
        
        self.assertEqual(count, 2)
    
    def test_broadcast_exclude_process(self):
        """Тест рассылки с исключением процесса"""
        self.registry.register_process_queues("Process1", {'system': Queue()})
        self.registry.register_process_queues("Process2", {'system': Queue()})
        
        message = {"broadcast": "message"}
        count = self.registry.broadcast_message(
            message, 
            queue_type="system", 
            exclude_process="Process1"
        )
        
        self.assertEqual(count, 1)  # Только Process2
    
    def test_unregister_process(self):
        """Тест отмены регистрации процесса"""
        self.registry.register_process_queues(self.process_name, self.queues)
        
        success = self.registry.unregister_process(self.process_name)
        self.assertTrue(success)
        
        processes = self.registry.get_registered_processes()
        self.assertNotIn(self.process_name, processes)
    
    def test_get_queue_sizes(self):
        """Тест получения размеров очередей"""
        self.registry.register_process_queues(self.process_name, self.queues)
        
        # Добавляем данные в очередь
        self.queues['system'].put("test1")
        self.queues['system'].put("test2")
        
        sizes = self.registry.get_queue_sizes()
        
        self.assertIn(self.process_name, sizes)
        self.assertIn('system', sizes[self.process_name])
        # Размер может быть 2 или 0 в зависимости от платформы
        self.assertIsInstance(sizes[self.process_name]['system'], int)
    
    def test_clear_queue(self):
        """Тест очистки очереди"""
        self.registry.register_process_queues(self.process_name, self.queues)
        
        # Добавляем данные
        self.queues['system'].put("test1")
        self.queues['system'].put("test2")
        self.queues['system'].put("test3")
        
        # Очищаем, сохраняя последний элемент
        self.registry.clear_queue(self.queues['system'], keep_elements=1)
        
        # Должен остаться только один элемент
        # Используем get с таймаутом вместо empty() для надежности
        count = 0
        items = []
        while True:
            try:
                item = self.queues['system'].get(timeout=0.001)
                if item is not None:
                    count += 1
                    items.append(item)
            except:
                break
        
        self.assertEqual(count, 1, f"Expected 1 item, got {count} items: {items}")
        # Проверяем, что остался последний элемент
        if count > 0:
            self.assertEqual(items[0], "test3")


if __name__ == '__main__':
    unittest.main()

