"""
Тесты для каналов логирования.

Проверяет:
- Создание разных типов каналов
- Запись в файл
- Запись в консоль
- HTTP канал (моки)
"""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from multiprocess_framework.modules.Logger_module.channels import (
    create_channel,
    FileChannel,
    ConsoleChannel,
    HttpChannel,
    LogChannel
)
from multiprocess_framework.modules.Logger_module.config import ChannelConfig


class TestFileChannel:
    """Тесты для FileChannel"""
    
    @pytest.fixture
    def temp_dir(self):
        """Фикстура для временной директории"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        import shutil
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def log_file(self, temp_dir):
        """Фикстура для файла лога"""
        return Path(temp_dir) / "test.log"
    
    @pytest.fixture
    def file_config(self, log_file):
        """Фикстура для конфигурации файлового канала"""
        return ChannelConfig(
            name='test_file',
            type='file',
            file_path=str(log_file),
            format='%(message)s'
        )
    
    def test_file_channel_creation(self, file_config, log_file):
        """Тест создания файлового канала"""
        channel = FileChannel(file_config)
        
        assert channel.name == 'test_file'
        assert channel.handler is not None
        assert log_file.parent.exists()
    
    def test_file_channel_write(self, file_config, log_file):
        """Тест записи в файл"""
        channel = FileChannel(file_config)
        
        record = {
            'timestamp': 1234567890.0,
            'level': 'INFO',
            'module': 'test_module',
            'message': 'Test message'
        }
        
        result = channel.write(record)
        
        assert result['status'] == 'success'
        assert result['channel'] == 'test_file'
        assert log_file.exists()
    
    def test_file_channel_close(self, file_config):
        """Тест закрытия файлового канала"""
        channel = FileChannel(file_config)
        channel.write({'timestamp': 1234567890.0, 'level': 'INFO', 'module': 'test', 'message': 'test'})
        
        # Закрываем канал
        channel.close()
        
        # Не должно быть ошибок
        assert channel.handler is not None


class TestConsoleChannel:
    """Тесты для ConsoleChannel"""
    
    @pytest.fixture
    def console_config(self):
        """Фикстура для конфигурации консольного канала"""
        return ChannelConfig(
            name='test_console',
            type='console',
            format='%(message)s'
        )
    
    def test_console_channel_creation(self, console_config):
        """Тест создания консольного канала"""
        channel = ConsoleChannel(console_config)
        
        assert channel.name == 'test_console'
        assert channel.handler is not None
    
    def test_console_channel_write(self, console_config):
        """Тест записи в консоль"""
        channel = ConsoleChannel(console_config)
        
        record = {
            'timestamp': 1234567890.0,
            'level': 'INFO',
            'module': 'test_module',
            'message': 'Test message'
        }
        
        result = channel.write(record)
        
        assert result['status'] == 'success'
        assert result['channel'] == 'test_console'


class TestHttpChannel:
    """Тесты для HttpChannel"""
    
    @pytest.fixture
    def http_config(self):
        """Фикстура для конфигурации HTTP канала"""
        return ChannelConfig(
            name='test_http',
            type='http',
            url='https://example.com/logs',
            headers={'Authorization': 'Bearer token'}
        )
    
    @patch('src.Modules.Logger_module.channels.requests.post')
    def test_http_channel_write_success(self, mock_post, http_config):
        """Тест успешной отправки HTTP запроса"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        channel = HttpChannel(http_config)
        
        record = {
            'timestamp': 1234567890.0,
            'level': 'INFO',
            'module': 'test_module',
            'message': 'Test message'
        }
        
        result = channel.write(record)
        
        assert result['status'] == 'success'
        assert result['channel'] == 'test_http'
        mock_post.assert_called_once()
        mock_response.raise_for_status.assert_called_once()
    
    @patch('src.Modules.Logger_module.channels.requests.post')
    def test_http_channel_write_error(self, mock_post, http_config):
        """Тест обработки ошибки HTTP запроса"""
        mock_post.side_effect = Exception("Connection error")
        
        channel = HttpChannel(http_config)
        
        record = {
            'timestamp': 1234567890.0,
            'level': 'INFO',
            'module': 'test_module',
            'message': 'Test message'
        }
        
        result = channel.write(record)
        
        assert result['status'] == 'error'
        assert 'error' in result


class TestChannelFactory:
    """Тесты для фабрики каналов"""
    
    def test_create_file_channel(self):
        """Тест создания файлового канала через фабрику"""
        config = ChannelConfig(
            name='file',
            type='file',
            file_path='logs/test.log'
        )
        
        channel = create_channel(config)
        assert isinstance(channel, FileChannel)
    
    def test_create_console_channel(self):
        """Тест создания консольного канала через фабрику"""
        config = ChannelConfig(
            name='console',
            type='console'
        )
        
        channel = create_channel(config)
        assert isinstance(channel, ConsoleChannel)
    
    def test_create_http_channel(self):
        """Тест создания HTTP канала через фабрику"""
        config = ChannelConfig(
            name='http',
            type='http',
            url='https://example.com/logs'
        )
        
        channel = create_channel(config)
        assert isinstance(channel, HttpChannel)
    
    def test_create_unknown_channel(self):
        """Тест создания неизвестного типа канала"""
        config = ChannelConfig(
            name='unknown',
            type='unknown_type'
        )
        
        with pytest.raises(ValueError):
            create_channel(config)
