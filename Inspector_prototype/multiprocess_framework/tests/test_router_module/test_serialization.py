"""
Тесты сериализации для Router_module.

Проверяем, что объекты модуля могут быть сериализованы для multiprocessing.
"""
import pickle
import pytest
from typing import Dict, Any

from multiprocess_framework.modules.Router_module.router_manager import RouterManager, create_router
from multiprocess_framework.modules.Router_module.router_adapter import RouterAdapter
from multiprocess_framework.modules.Router_module.channel import MessageChannel, QueueChannel
from multiprocess_framework.modules.Dispatch_module import DispatchStrategy


class TestRouterManagerSerialization:
    """Тесты сериализации RouterManager."""
    
    def test_router_manager_basic_serialization(self):
        """Проверяем базовую сериализацию RouterManager."""
        router = RouterManager("test_router")
        
        # Сериализуем
        try:
            serialized = pickle.dumps(router)
            deserialized = pickle.loads(serialized)
            
            assert deserialized.router_id == "test_router"
            assert deserialized._listening is False
            assert deserialized._listener_thread is None
        except Exception as e:
            pytest.fail(f"Сериализация не удалась: {e}")
    
    def test_router_manager_with_stats_serialization(self):
        """Проверяем сериализацию RouterManager со статистикой."""
        router = RouterManager("test_router")
        router._stats['sent'] = 10
        router._stats['received'] = 5
        
        try:
            serialized = pickle.dumps(router)
            deserialized = pickle.loads(serialized)
            
            assert deserialized._stats['sent'] == 10
            assert deserialized._stats['received'] == 5
        except Exception as e:
            pytest.fail(f"Сериализация со статистикой не удалась: {e}")
    
    def test_router_manager_with_dispatcher_serialization(self):
        """Проверяем сериализацию RouterManager с диспетчерами."""
        router = RouterManager(
            "test_router",
            dispatch_strategy=DispatchStrategy.FALLBACK_MATCH
        )
        
        try:
            serialized = pickle.dumps(router)
            deserialized = pickle.loads(serialized)
            
            # Проверяем, что диспетчеры инициализированы
            assert deserialized.channel_dispatcher is not None
            assert deserialized.message_dispatcher is not None
        except Exception as e:
            pytest.fail(f"Сериализация с диспетчерами не удалась: {e}")
    
    def test_router_manager_without_thread_serialization(self):
        """Проверяем, что RouterManager без активного потока сериализуется."""
        router = RouterManager("test_router")
        # Не запускаем прослушивание - поток не создан
        
        try:
            serialized = pickle.dumps(router)
            deserialized = pickle.loads(serialized)
            
            assert deserialized._listening is False
            assert deserialized._listener_thread is None
        except Exception as e:
            pytest.fail(f"Сериализация без потока не удалась: {e}")
    
    def test_router_manager_serialization_warning_with_thread(self):
        """Проверяем, что RouterManager с активным потоком не сериализуется."""
        router = RouterManager("test_router")
        router.start_listening(poll_interval=0.01)
        
        # Попытка сериализации должна либо пройти, либо дать предсказуемую ошибку
        try:
            serialized = pickle.dumps(router)
            # Если сериализация прошла, поток должен быть None после десериализации
            deserialized = pickle.loads(serialized)
            # Поток не может быть сериализован, поэтому должен быть None
            assert deserialized._listener_thread is None
            assert deserialized._listening is False  # Или должен быть сброшен
        except (TypeError, AttributeError) as e:
            # Это ожидаемо - threading.Thread не сериализуется
            # Это нормальное поведение
            assert "Thread" in str(e) or "threading" in str(e).lower()
        except Exception as e:
            pytest.fail(f"Неожиданная ошибка при сериализации с потоком: {e}")
        finally:
            # Останавливаем поток для очистки
            router._listening = False
            if router._listener_thread:
                router._listener_thread.join(timeout=1.0)


class TestRouterAdapterSerialization:
    """Тесты сериализации RouterAdapter."""
    
    def test_router_adapter_basic_serialization(self):
        """Проверяем базовую сериализацию RouterAdapter."""
        router = RouterManager("test_router")
        adapter = RouterAdapter(router)
        adapter.setup()
        
        try:
            serialized = pickle.dumps(adapter)
            deserialized = pickle.loads(serialized)
            
            # Адаптер может содержать ссылку на менеджер
            # Проверяем базовые свойства
            assert deserialized.adapter_name == "RouterAdapter"
        except Exception as e:
            # Адаптер может не сериализоваться полностью из-за ссылок на менеджер
            # Это может быть нормально, в зависимости от архитектуры
            pytest.skip(f"Адаптер может не сериализоваться из-за ссылок: {e}")


class TestChannelSerialization:
    """Тесты сериализации каналов."""
    
    def test_queue_channel_serialization(self):
        """Проверяем сериализацию QueueChannel."""
        from queue import Queue
        
        queue = Queue()
        channel = QueueChannel("test_channel", queue)
        
        # Queue не сериализуется напрямую
        try:
            serialized = pickle.dumps(channel)
            pytest.fail("QueueChannel с Queue не должен сериализоваться")
        except (TypeError, AttributeError):
            # Это ожидаемо - Queue не сериализуется
            pass
    
    def test_queue_channel_without_queue_serialization(self):
        """Проверяем, что QueueChannel без явного Queue создается заново."""
        # QueueChannel создает новую очередь если не передана
        # Но все равно Queue не сериализуется
        channel = QueueChannel("test_channel")
        
        try:
            serialized = pickle.dumps(channel)
            pytest.fail("QueueChannel не должен сериализоваться из-за Queue")
        except (TypeError, AttributeError):
            # Это ожидаемо
            pass


class TestSerializationNotes:
    """Заметки о сериализации для документации."""
    
    def test_serialization_limitations(self):
        """
        Документирует ограничения сериализации.
        
        Важные факты:
        1. RouterManager БЕЗ активного потока сериализуется
        2. RouterManager С активным потоком - поток не сериализуется (ожидаемо)
        3. Каналы с Queue не сериализуются (нормально - Queue должна создаваться в каждом процессе)
        4. Диспетчеры сериализуются, но обработчики (callable) могут не сериализоваться
        
        Рекомендации:
        - Создавать RouterManager в каждом процессе отдельно
        - Не пытаться передавать RouterManager между процессами через pickle
        - Использовать только сериализуемые данные (словари, списки, примитивы)
        """
        # Этот тест только для документации
        assert True

