"""
Тесты для модуля channel.py - базовый интерфейс и реализации каналов.
"""
import pytest
import time
from queue import Queue, Empty
from unittest.mock import Mock

from multiprocess_framework.modules.Router_module.channel import MessageChannel, QueueChannel


class TestMessageChannelInterface:
    """Тесты базового интерфейса MessageChannel."""
    
    def test_message_channel_is_abstract(self):
        """Проверяем, что MessageChannel - абстрактный класс."""
        with pytest.raises(TypeError):
            MessageChannel()
    
    def test_message_channel_abstract_methods(self):
        """Проверяем наличие абстрактных методов."""
        assert hasattr(MessageChannel, 'name')
        assert hasattr(MessageChannel, 'channel_type')
        assert hasattr(MessageChannel, 'send')
        assert hasattr(MessageChannel, 'poll')
    
    def test_message_channel_default_methods(self):
        """Проверяем методы по умолчанию."""
        # Проверяем, что start_listening возвращает False по умолчанию
        class TestChannel(MessageChannel):
            @property
            def name(self):
                return "test"
            
            @property
            def channel_type(self):
                return "test"
            
            def send(self, message):
                return {"status": "success"}
            
            def poll(self, timeout=0.0):
                return []
        
        channel = TestChannel()
        assert channel.start_listening(lambda x: None) is False
        assert channel.stop_listening() is True
        assert 'name' in channel.get_info()
        assert 'type' in channel.get_info()


class TestQueueChannel:
    """Тесты для QueueChannel."""
    
    def test_queue_channel_initialization(self):
        """Проверяем инициализацию QueueChannel."""
        channel = QueueChannel("test_channel")
        
        assert channel.name == "test_channel"
        assert channel.channel_type == "queue"
        assert channel._listening is False
        assert channel._listener_thread is None
    
    def test_queue_channel_initialization_with_queue(self):
        """Проверяем инициализацию с существующей очередью."""
        queue = Queue()
        channel = QueueChannel("test_channel", queue)
        
        assert channel._queue == queue
    
    def test_queue_channel_send(self):
        """Проверяем отправку сообщения."""
        channel = QueueChannel("test_channel")
        message = {'data': 'test'}
        
        result = channel.send(message)
        
        assert result['status'] == 'success'
        assert result['channel'] == 'test_channel'
        assert channel._queue.qsize() == 1
    
    def test_queue_channel_send_error_handling(self):
        """Проверяем обработку ошибок при отправке."""
        # Создаем канал с мокированной очередью
        channel = QueueChannel("test_channel")
        
        # Ломаем очередь
        original_put = channel._queue.put
        channel._queue.put = Mock(side_effect=Exception("Queue error"))
        
        result = channel.send({'data': 'test'})
        
        assert result['status'] == 'error'
        assert 'Queue error' in result['reason']
        
        # Восстанавливаем
        channel._queue.put = original_put
    
    def test_queue_channel_poll_non_blocking(self):
        """Проверяем non-blocking опрос."""
        channel = QueueChannel("test_channel")
        
        # Очередь пуста
        messages = channel.poll(timeout=0.0)
        assert messages == []
        
        # Добавляем сообщение
        channel.send({'data': 'test1'})
        channel.send({'data': 'test2'})
        
        messages = channel.poll(timeout=0.0)
        
        assert len(messages) == 2
        assert messages[0]['data'] == 'test1'
        assert messages[1]['data'] == 'test2'
    
    def test_queue_channel_poll_blocking(self):
        """Проверяем blocking опрос с таймаутом."""
        channel = QueueChannel("test_channel")
        
        # Запускаем опрос в отдельном потоке
        import threading
        received_messages = []
        
        def poll_worker():
            messages = channel.poll(timeout=0.1)
            received_messages.extend(messages)
        
        thread = threading.Thread(target=poll_worker)
        thread.start()
        
        # Даем время на запуск
        time.sleep(0.01)
        
        # Отправляем сообщение
        channel.send({'data': 'test'})
        
        thread.join(timeout=1.0)
        
        assert len(received_messages) >= 1
        assert received_messages[0]['data'] == 'test'
    
    def test_queue_channel_poll_empty_timeout(self):
        """Проверяем опрос с таймаутом на пустой очереди."""
        channel = QueueChannel("test_channel")
        
        start_time = time.time()
        messages = channel.poll(timeout=0.1)
        elapsed = time.time() - start_time
        
        assert messages == []
        assert 0.05 <= elapsed <= 0.15  # Допускаем небольшую погрешность
    
    def test_queue_channel_start_listening(self):
        """Проверяем запуск прослушивания."""
        channel = QueueChannel("test_channel")
        
        callback_called = []
        
        def callback(message):
            callback_called.append(message)
        
        result = channel.start_listening(callback)
        
        assert result is True
        assert channel._listening is True
        assert channel._listener_thread is not None
        assert channel._listener_thread.is_alive()
        
        # Отправляем сообщение
        channel.send({'data': 'test'})
        
        # Ждем обработки
        time.sleep(0.2)
        
        # Останавливаем
        channel.stop_listening()
        
        assert len(callback_called) >= 1
    
    def test_queue_channel_start_listening_already_listening(self):
        """Проверяем запуск прослушивания, если уже слушает."""
        channel = QueueChannel("test_channel")
        
        def callback(message):
            pass
        
        channel.start_listening(callback)
        result = channel.start_listening(callback)
        
        assert result is False
        
        channel.stop_listening()
    
    def test_queue_channel_stop_listening(self):
        """Проверяем остановку прослушивания."""
        channel = QueueChannel("test_channel")
        
        def callback(message):
            pass
        
        channel.start_listening(callback)
        assert channel._listening is True
        
        result = channel.stop_listening()
        
        assert result is True
        assert channel._listening is False
        
        # Проверяем, что поток остановлен
        if channel._listener_thread:
            channel._listener_thread.join(timeout=1.0)
            assert not channel._listener_thread.is_alive()
    
    def test_queue_channel_stop_listening_not_listening(self):
        """Проверяем остановку прослушивания, если не слушает."""
        channel = QueueChannel("test_channel")
        
        result = channel.stop_listening()
        
        assert result is True
    
    def test_queue_channel_get_info(self):
        """Проверяем получение информации о канале."""
        channel = QueueChannel("test_channel")
        
        info = channel.get_info()
        
        assert info['name'] == 'test_channel'
        assert info['type'] == 'queue'
        assert info['active'] is True
        assert 'queue_size' in info
        assert 'listening' in info
        assert info['listening'] is False
    
    def test_queue_channel_get_info_with_messages(self):
        """Проверяем информацию о канале с сообщениями."""
        channel = QueueChannel("test_channel")
        channel.send({'data': 'test1'})
        channel.send({'data': 'test2'})
        
        info = channel.get_info()
        
        assert info['queue_size'] == 2
    
    def test_queue_channel_get_info_while_listening(self):
        """Проверяем информацию о канале во время прослушивания."""
        channel = QueueChannel("test_channel")
        
        def callback(message):
            pass
        
        channel.start_listening(callback)
        
        info = channel.get_info()
        assert info['listening'] is True
        
        channel.stop_listening()
    
    def test_queue_channel_listener_error_handling(self):
        """Проверяем обработку ошибок в цикле прослушивания."""
        channel = QueueChannel("test_channel")
        
        callback_called = []
        
        def callback(message):
            callback_called.append(message)
            if len(callback_called) == 1:
                raise Exception("Callback error")
        
        channel.start_listening(callback)
        
        # Отправляем несколько сообщений
        channel.send({'data': 'test1'})
        channel.send({'data': 'test2'})
        
        time.sleep(0.2)
        
        # Ошибка в колбэке не должна остановить прослушивание
        assert channel._listening is True
        
        channel.stop_listening()
        
        # Хотя бы одно сообщение должно быть обработано
        assert len(callback_called) >= 1

