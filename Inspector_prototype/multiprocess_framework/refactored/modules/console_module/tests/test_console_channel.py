"""
Тесты для ConsoleChannel.
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Добавляем путь к модулю для абсолютных импортов
module_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(module_path))

from src.multiprocess_framework.refactored.modules.console_module.channels.console_channel import ConsoleChannel


class TestConsoleChannel(unittest.TestCase):
    """Тесты для ConsoleChannel."""
    
    def setUp(self):
        """Подготовка к тестам."""
        self.console_manager = Mock()
        self.console_manager._send_to_console = Mock(return_value=True)
        self.channel_name = "console.TestProcess"
        self.target_process = "TestProcess"
    
    def test_init(self):
        """Тест инициализации."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager,
            target_process=self.target_process
        )
        
        self.assertEqual(channel.name, self.channel_name)
        self.assertEqual(channel._target_process, self.target_process)
        self.assertEqual(channel.channel_type, "console")
    
    def test_send_success(self):
        """Тест успешной отправки сообщения."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager,
            target_process=self.target_process
        )
        
        message = {
            'text': 'Test message',
            'level': 'INFO'
        }
        
        result = channel.send(message)
        
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['channel'], self.channel_name)
        self.console_manager._send_to_console.assert_called_once()
    
    def test_send_with_timestamp(self):
        """Тест отправки с временной меткой."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager
        )
        
        message = {
            'text': 'Test message',
            'level': 'INFO',
            'timestamp': True
        }
        
        result = channel.send(message)
        self.assertEqual(result['status'], 'success')
    
    def test_send_with_different_levels(self):
        """Тест отправки с разными уровнями."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager
        )
        
        levels = ['INFO', 'WARNING', 'ERROR', 'DEBUG']
        for level in levels:
            message = {'text': f'Test {level}', 'level': level}
            result = channel.send(message)
            self.assertEqual(result['status'], 'success')
    
    def test_send_no_text(self):
        """Тест отправки без текста."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager
        )
        
        message = {}
        result = channel.send(message)
        
        self.assertEqual(result['status'], 'error')
        self.assertIn('reason', result)
    
    def test_send_alternative_fields(self):
        """Тест отправки с альтернативными полями."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager
        )
        
        # Тест с полем 'message'
        message1 = {'message': 'Test message'}
        result1 = channel.send(message1)
        self.assertEqual(result1['status'], 'success')
        
        # Тест с полем 'content'
        message2 = {'content': 'Test content'}
        result2 = channel.send(message2)
        self.assertEqual(result2['status'], 'success')
    
    def test_send_with_target_process(self):
        """Тест отправки с указанием процесса."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager,
            target_process=self.target_process
        )
        
        message = {
            'text': 'Test message',
            'process': 'OtherProcess'  # Переопределяет target_process
        }
        
        result = channel.send(message)
        self.assertEqual(result['status'], 'success')
    
    def test_send_error(self):
        """Тест обработки ошибки при отправке."""
        self.console_manager._send_to_console.side_effect = Exception("Test error")
        
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager
        )
        
        message = {'text': 'Test message'}
        result = channel.send(message)
        
        self.assertEqual(result['status'], 'error')
        self.assertIn('reason', result)
    
    def test_poll(self):
        """Тест опроса канала."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager
        )
        
        result = channel.poll()
        self.assertEqual(result, [])
    
    def test_get_info(self):
        """Тест получения информации о канале."""
        channel = ConsoleChannel(
            name=self.channel_name,
            console_manager=self.console_manager,
            target_process=self.target_process,
            target_console="TestConsole"
        )
        
        info = channel.get_info()
        
        self.assertEqual(info['name'], self.channel_name)
        self.assertEqual(info['type'], 'console')
        self.assertEqual(info['target_process'], self.target_process)
        self.assertEqual(info['target_console'], "TestConsole")
        self.assertTrue(info['active'])


if __name__ == '__main__':
    unittest.main()

