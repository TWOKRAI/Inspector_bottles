"""
Тесты для ConsoleRedirector.
"""
import unittest
import sys
from pathlib import Path
from multiprocessing import Queue

# Добавляем путь к модулю для абсолютных импортов
module_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(module_path))

from src.multiprocess_framework.refactored.modules.console_module.redirectors.console_redirector import ConsoleRedirector


class TestConsoleRedirector(unittest.TestCase):
    """Тесты для ConsoleRedirector."""
    
    def setUp(self):
        """Подготовка к тестам."""
        self.output_queue = Queue()
        self.process_name = "TestProcess"
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
    
    def tearDown(self):
        """Очистка после тестов."""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
    
    def test_init_single_queue(self):
        """Тест инициализации с одной очередью."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        self.assertEqual(len(redirector.output_queues), 1)
        self.assertEqual(redirector.process_name, self.process_name)
        self.assertFalse(redirector._closed)
    
    def test_init_multiple_queues(self):
        """Тест инициализации с несколькими очередями."""
        queues = [Queue(), Queue(), Queue()]
        redirector = ConsoleRedirector(queues, self.process_name)
        self.assertEqual(len(redirector.output_queues), 3)
    
    def test_write(self):
        """Тест записи данных."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        redirector.write("test message\n")
        
        # Проверяем что сообщение попало в очередь
        stream_type, data = self.output_queue.get(timeout=1.0)
        self.assertEqual(stream_type, 'stdout')
        self.assertIn(self.process_name, data)
        self.assertIn("test message", data)
    
    def test_write_empty(self):
        """Тест записи пустых данных."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        redirector.write("")
        
        # Очередь должна быть пустой
        self.assertTrue(self.output_queue.empty())
    
    def test_write_bytes(self):
        """Тест записи байтов."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        redirector.write(b"test bytes\n")
        
        stream_type, data = self.output_queue.get(timeout=1.0)
        self.assertEqual(stream_type, 'stdout')
        self.assertIsInstance(data, str)
    
    def test_flush(self):
        """Тест сброса буфера."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        redirector.flush()
        
        stream_type, data = self.output_queue.get(timeout=1.0)
        self.assertEqual(stream_type, 'flush')
    
    def test_close(self):
        """Тест закрытия."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        redirector.close()
        
        self.assertTrue(redirector._closed)
        
        # Проверяем что сообщение о закрытии попало в очередь
        stream_type, data = self.output_queue.get(timeout=1.0)
        self.assertEqual(stream_type, 'close')
    
    def test_restore(self):
        """Тест восстановления оригинальных потоков."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        sys.stdout = redirector
        
        result = redirector.restore()
        self.assertTrue(result)
        self.assertEqual(sys.stdout, self.original_stdout)
    
    def test_write_after_close(self):
        """Тест записи после закрытия."""
        redirector = ConsoleRedirector(self.output_queue, self.process_name)
        redirector.close()
        redirector.write("should not appear\n")
        
        # Очищаем очередь от сообщения о закрытии
        self.output_queue.get(timeout=1.0)
        
        # Очередь должна быть пустой
        self.assertTrue(self.output_queue.empty())


if __name__ == '__main__':
    unittest.main()

