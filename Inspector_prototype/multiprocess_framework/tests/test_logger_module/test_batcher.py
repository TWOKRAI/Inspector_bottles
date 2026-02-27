"""
Тесты для BatchManager.

Проверяет:
- Группировку сообщений в пачки
- Сброс по размеру
- Сброс по времени
- Приоритетный сброс для ошибок
- Статистику
"""
import pytest
import time
from unittest.mock import Mock

from multiprocess_framework.modules.Logger_module.batcher import BatchManager, BatchConfig


class TestBatchManager:
    """Тесты для BatchManager"""
    
    def test_initialization(self, flush_callback, batch_config):
        """Тест инициализации BatchManager"""
        batcher = BatchManager(flush_callback, batch_config)
        
        assert batcher is not None
        assert batcher.config.max_size == 5
        assert batcher.config.flush_interval == 0.1
        assert batcher.stats['total_messages'] == 0
        assert batcher.stats['total_batches'] == 0
    
    def test_add_message(self, flush_callback, batch_config):
        """Тест добавления сообщения"""
        batcher = BatchManager(flush_callback, batch_config)
        message = {'level': 'INFO', 'message': 'Test'}
        
        batcher.add_message('test_channel', message)
        
        assert len(batcher.batches['test_channel']) == 1
        assert batcher.stats['total_messages'] == 1
    
    def test_flush_by_size(self, flush_callback, batch_config):
        """Тест сброса по размеру"""
        batcher = BatchManager(flush_callback, batch_config)
        
        # Добавляем сообщения до достижения max_size
        for i in range(5):
            batcher.add_message('test_channel', {'level': 'INFO', 'message': f'Message {i}'})
        
        # Проверяем, что был вызван flush_callback
        assert flush_callback.call_count == 1
        
        # Проверяем, что пачка была передана
        call_args = flush_callback.call_args
        assert call_args[0][0] == 'test_channel'
        assert len(call_args[0][1]) == 5
        
        # Проверяем статистику
        assert batcher.stats['total_batches'] == 1
        assert batcher.stats['total_messages'] == 5
    
    def test_priority_flush(self, flush_callback, batch_config):
        """Тест приоритетного сброса для ошибок"""
        batcher = BatchManager(flush_callback, batch_config)
        
        # Добавляем обычное сообщение
        batcher.add_message('test_channel', {'level': 'INFO', 'message': 'Info'})
        
        # Добавляем ошибку - должна сразу сброситься
        batcher.add_message('test_channel', {'level': 'ERROR', 'message': 'Error'})
        
        # Проверяем, что был вызван flush_callback
        assert flush_callback.call_count >= 1
        
        # Проверяем, что в пачке было сообщение
        call_args = flush_callback.call_args_list[0]
        batch = call_args[0][1]
        assert len(batch) >= 1
    
    def test_flush_by_time(self, flush_callback, batch_config):
        """Тест сброса по времени"""
        batcher = BatchManager(flush_callback, batch_config)
        
        # Добавляем сообщение
        batcher.add_message('test_channel', {'level': 'INFO', 'message': 'Test'})
        
        # Ждем больше flush_interval
        time.sleep(0.15)
        
        # Добавляем еще одно сообщение - должно сбросить предыдущее
        batcher.add_message('test_channel', {'level': 'INFO', 'message': 'Test2'})
        
        # Проверяем, что был вызван flush_callback
        assert flush_callback.call_count >= 1
    
    def test_multiple_channels(self, flush_callback, batch_config):
        """Тест работы с несколькими каналами"""
        batcher = BatchManager(flush_callback, batch_config)
        
        batcher.add_message('channel1', {'level': 'INFO', 'message': 'Message 1'})
        batcher.add_message('channel2', {'level': 'INFO', 'message': 'Message 2'})
        
        assert len(batcher.batches['channel1']) == 1
        assert len(batcher.batches['channel2']) == 1
        assert batcher.stats['total_messages'] == 2
    
    def test_flush_all(self, flush_callback, batch_config):
        """Тест принудительного сброса всех пачек"""
        batcher = BatchManager(flush_callback, batch_config)
        
        # Добавляем сообщения в разные каналы
        for i in range(3):
            batcher.add_message('channel1', {'level': 'INFO', 'message': f'Message {i}'})
            batcher.add_message('channel2', {'level': 'INFO', 'message': f'Message {i}'})
        
        # Принудительно сбрасываем все
        batcher.flush_all()
        
        # Проверяем, что все пачки пустые
        assert len(batcher.batches['channel1']) == 0
        assert len(batcher.batches['channel2']) == 0
        
        # Проверяем, что flush_callback был вызван для каждого канала
        assert flush_callback.call_count >= 2
    
    def test_statistics(self, flush_callback, batch_config):
        """Тест сбора статистики"""
        batcher = BatchManager(flush_callback, batch_config)
        
        # Добавляем несколько пачек
        for _ in range(3):
            for i in range(5):
                batcher.add_message('test_channel', {'level': 'INFO', 'message': f'Message {i}'})
        
        # Проверяем статистику
        assert batcher.stats['total_batches'] == 3
        assert batcher.stats['total_messages'] == 15
        assert batcher.stats['avg_batch_size'] > 0
    
    def test_flush_empty_channel(self, flush_callback, batch_config):
        """Тест сброса пустого канала"""
        batcher = BatchManager(flush_callback, batch_config)
        
        # Пытаемся сбросить несуществующий канал
        batcher._flush_channel('non_existent')
        
        # Не должно быть ошибок
        assert flush_callback.call_count == 0
    
    def test_critical_level_flush(self, flush_callback, batch_config):
        """Тест сброса для критических сообщений"""
        batcher = BatchManager(flush_callback, batch_config)
        
        # Добавляем обычное сообщение
        batcher.add_message('test_channel', {'level': 'INFO', 'message': 'Info'})
        
        # Добавляем критическое сообщение
        batcher.add_message('test_channel', {'level': 'CRITICAL', 'message': 'Critical'})
        
        # Проверяем, что был вызван flush_callback
        assert flush_callback.call_count >= 1
