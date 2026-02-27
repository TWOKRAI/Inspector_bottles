"""
Тесты для ConsoleManager.
"""

import pytest
import time
from multiprocessing import Queue
from multiprocess_framework.modules.Console_module.console_manager import ConsoleManager


class TestConsoleManagerBasic:
    """Базовые тесты ConsoleManager"""
    
    def test_init(self, console_manager):
        """Тест инициализации"""
        assert console_manager is not None
        assert console_manager.logger is not None
    
    def test_configure_process_console_single(self, console_manager):
        """Тест настройки отдельной консоли"""
        console_manager.configure_process_console("Process1", enabled=True)
        
        assert "Process1" in console_manager._process_groups
        assert console_manager._process_groups["Process1"] == "Process1"
    
    def test_configure_process_console_group(self, console_manager):
        """Тест настройки групповой консоли"""
        console_manager.configure_process_console("Process1", enabled=True, group="workers")
        console_manager.configure_process_console("Process2", enabled=True, group="workers")
        
        assert "Process1" in console_manager._process_groups
        assert "Process2" in console_manager._process_groups
        assert console_manager._process_groups["Process1"] == "workers"
        assert console_manager._process_groups["Process2"] == "workers"
        assert "workers" in console_manager._group_consoles
        assert "Process1" in console_manager._group_consoles["workers"]
        assert "Process2" in console_manager._group_consoles["workers"]
    
    def test_configure_process_console_disabled(self, console_manager):
        """Тест отключения консоли"""
        console_manager.configure_process_console("Process1", enabled=True)
        assert "Process1" in console_manager._process_groups
        
        console_manager.configure_process_console("Process1", enabled=False)
        assert "Process1" not in console_manager._process_groups
    
    def test_configure_with_title(self, console_manager):
        """Тест настройки с кастомным заголовком"""
        console_manager.configure_process_console(
            "Process1", 
            enabled=True, 
            title="Custom Title"
        )
        
        assert console_manager._console_titles.get("Process1") == "Custom Title"
    
    def test_create_process_console_single(self, console_manager):
        """Тест создания отдельной консоли"""
        console_manager.configure_process_console("Process1", enabled=True)
        result = console_manager.create_process_console("Process1")
        
        assert result is True
        assert "Process1" in console_manager._process_queues
        assert "Process1" in console_manager._console_processes
        assert "Process1" in console_manager._visible_consoles
    
    def test_create_process_console_group(self, console_manager):
        """Тест создания групповой консоли"""
        console_manager.configure_process_console("Process1", enabled=True, group="workers")
        console_manager.configure_process_console("Process2", enabled=True, group="workers")
        
        result1 = console_manager.create_process_console("Process1")
        result2 = console_manager.create_process_console("Process2")
        
        assert result1 is True
        assert result2 is True
        
        # Оба процесса должны использовать один queue
        queue1 = console_manager._process_queues.get("Process1")
        queue2 = console_manager._process_queues.get("Process2")
        assert queue1 is not None
        assert queue2 is not None
        assert queue1 is queue2  # Один и тот же queue
    
    def test_create_console_not_configured(self, console_manager):
        """Тест создания консоли для не настроенного процесса"""
        result = console_manager.create_process_console("NonExistent")
        assert result is False
    
    def test_get_queue(self, console_manager):
        """Тест получения queue"""
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.create_process_console("Process1")
        
        queue = console_manager.get_queue("Process1")
        assert queue is not None
        # Проверяем что это queue-подобный объект (в Windows может быть прокси)
        assert hasattr(queue, 'put') and hasattr(queue, 'get')
        
        # Несуществующий процесс
        queue_none = console_manager.get_queue("NonExistent")
        assert queue_none is None
    
    def test_get_status(self, console_manager):
        """Тест получения статуса"""
        console_manager.configure_process_console("Process1", enabled=True, title="Test Title")
        console_manager.create_process_console("Process1")
        
        status = console_manager.get_status("Process1")
        
        assert status['has_console'] is True
        assert status['visible'] is True
        assert status['group'] == "Process1"
        assert status['title'] == "Test Title"
    
    def test_setup_redirect(self, console_manager):
        """Тест настройки перенаправления"""
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.create_process_console("Process1")
        
        redirector = console_manager.setup_redirect("Process1")
        
        assert redirector is not None
        assert redirector.process_name == "Process1"
        assert "Process1" in console_manager._redirectors
        
        # Несуществующий процесс
        redirector_none = console_manager.setup_redirect("NonExistent")
        assert redirector_none is None
    
    def test_close_all(self, console_manager):
        """Тест закрытия всех консолей"""
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.configure_process_console("Process2", enabled=True, group="workers")
        console_manager.create_process_console("Process1")
        console_manager.create_process_console("Process2")
        
        console_manager.close_all()
        
        assert len(console_manager._process_queues) == 0
        assert len(console_manager._group_consoles) == 0
        assert len(console_manager._console_processes) == 0


class TestCustomChannels:
    """Тесты для кастомных каналов"""
    
    def test_create_custom_channel(self, console_manager):
        """Тест создания кастомного канала"""
        queue = console_manager.create_custom_channel(
            name="notifications",
            title="Notifications"
        )
        
        assert queue is not None
        # Проверяем что это queue-подобный объект (в Windows может быть прокси)
        assert hasattr(queue, 'put') and hasattr(queue, 'get')
        assert "notifications" in console_manager._custom_channels
        assert f"custom_notifications" in console_manager._console_processes
    
    def test_create_custom_channel_twice(self, console_manager):
        """Тест создания кастомного канала дважды (должен вернуть существующий)"""
        queue1 = console_manager.create_custom_channel("notifications")
        queue2 = console_manager.create_custom_channel("notifications")
        
        assert queue1 is queue2  # Один и тот же queue
    
    def test_get_custom_channel_queue(self, console_manager):
        """Тест получения queue кастомного канала"""
        queue = console_manager.create_custom_channel("notifications")
        
        retrieved_queue = console_manager.get_custom_channel_queue("notifications")
        assert retrieved_queue is not None
        assert retrieved_queue is queue
        
        # Несуществующий канал
        queue_none = console_manager.get_custom_channel_queue("non_existent")
        assert queue_none is None


class TestRouterIntegration:
    """Тесты интеграции с Router"""
    
    def test_register_in_router_basic(self, console_manager):
        """Тест базовой регистрации в роутере"""
        from multiprocess_framework.modules.Router_module.router_manager import RouterManager
        
        # Настраиваем консоли
        console_manager.configure_process_console("Process1", enabled=True, group="workers")
        console_manager.configure_process_console("Process2", enabled=True, group="workers")
        console_manager.create_process_console("Process1")
        console_manager.create_process_console("Process2")
        
        # Создаем кастомный канал
        console_manager.create_custom_channel("notifications")
        
        # Создаем роутер
        router = RouterManager("test_router")
        
        # Регистрируем
        channels = console_manager.register_in_router(router)
        
        assert len(channels) > 0
        assert "console.Process1" in channels
        assert "console.group.workers" in channels
        assert "console.all" in channels
        assert "console.notifications" in channels
        
        # Проверяем что каналы действительно зарегистрированы
        assert router.get_channel("console.Process1") is not None
        assert router.get_channel("console.group.workers") is not None
        assert router.get_channel("console.all") is not None
        assert router.get_channel("console.notifications") is not None
    
    def test_send_via_router(self, console_manager):
        """Тест отправки сообщения через роутер"""
        from multiprocess_framework.modules.Router_module.router_manager import RouterManager
        
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.create_process_console("Process1")
        
        router = RouterManager("test_router")
        console_manager.register_in_router(router)
        
        # Отправляем сообщение
        result = router.send({
            'channel': 'console.Process1',
            'text': 'Test message',
            'level': 'INFO'
        })
        
        assert result.get('status') == 'success'
        
        # Проверяем что сообщение попало в queue
        queue = console_manager.get_queue("Process1")
        assert queue is not None
        
        # Читаем сообщение из queue (с таймаутом)
        try:
            stream_type, data = queue.get(timeout=0.5)
            assert stream_type == 'stdout'
            assert 'Test message' in data
        except Exception:
            pytest.fail("Message not received in queue")


class TestConsoleChannel:
    """Тесты для ConsoleChannel"""
    
    def test_console_channel_send(self, console_manager):
        """Тест отправки через ConsoleChannel"""
        from multiprocess_framework.modules.Console_module import ConsoleChannel
        
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.create_process_console("Process1")
        
        channel = ConsoleChannel(
            name="test_channel",
            console_manager=console_manager,
            target_process="Process1"
        )
        
        result = channel.send({
            'text': 'Channel test message',
            'level': 'INFO',
            'timestamp': True
        })
        
        assert result.get('status') == 'success'
        
        # Проверяем queue
        queue = console_manager.get_queue("Process1")
        try:
            stream_type, data = queue.get(timeout=0.5)
            assert stream_type == 'stdout'
            assert 'Channel test message' in data
        except Exception:
            pytest.fail("Message not received")
    
    def test_console_channel_formatting(self, console_manager):
        """Тест форматирования сообщений"""
        from multiprocess_framework.modules.Console_module import ConsoleChannel
        
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.create_process_console("Process1")
        
        channel = ConsoleChannel(
            name="test_channel",
            console_manager=console_manager,
            target_process="Process1"
        )
        
        # Тест с timestamp
        result = channel.send({
            'text': 'Test',
            'timestamp': True,
            'level': 'WARNING'
        })
        
        assert result.get('status') == 'success'
        
        queue = console_manager.get_queue("Process1")
        try:
            stream_type, data = queue.get(timeout=0.5)
            assert '[WARNING]' in data
            # Проверяем что есть timestamp (формат HH:MM:SS)
            import re
            assert re.search(r'\[\d{2}:\d{2}:\d{2}\]', data) is not None
        except Exception:
            pytest.fail("Formatted message not received")


class TestRedirector:
    """Тесты для ConsoleRedirector"""
    
    def test_redirector_write(self, console_manager):
        """Тест записи через redirector"""
        from multiprocess_framework.modules.Console_module.redirector import ConsoleRedirector
        
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.create_process_console("Process1")
        
        queue = console_manager.get_queue("Process1")
        redirector = ConsoleRedirector(queue, "Process1")
        
        redirector.write("Test message\n")
        redirector.flush()
        
        try:
            stream_type, data = queue.get(timeout=0.5)
            assert stream_type == 'stdout'
            assert '[Process1]' in data
            assert 'Test message' in data
        except Exception:
            pytest.fail("Redirected message not received")
    
    def test_redirector_close(self, console_manager):
        """Тест закрытия redirector"""
        from multiprocess_framework.modules.Console_module.redirector import ConsoleRedirector
        import sys
        
        console_manager.configure_process_console("Process1", enabled=True)
        console_manager.create_process_console("Process1")
        
        queue = console_manager.get_queue("Process1")
        original_stdout = sys.stdout
        
        redirector = ConsoleRedirector(queue, "Process1")
        sys.stdout = redirector
        
        redirector.close()
        
        assert redirector._closed is True
        assert sys.stdout == redirector
        # При вызове close не восстанавливается автоматически
        # Это делается вручную в close_console


class TestIntegration:
    """Интеграционные тесты"""
    
    def test_full_workflow(self, console_manager):
        """Полный workflow: настройка -> создание -> использование"""
        # Настройка
        console_manager.configure_process_console("Worker1", enabled=True, group="workers")
        console_manager.configure_process_console("Worker2", enabled=True, group="workers")
        
        # Создание
        console_manager.create_process_console("Worker1")
        console_manager.create_process_console("Worker2")
        
        # Проверка
        assert console_manager.get_queue("Worker1") is not None
        assert console_manager.get_queue("Worker2") is not None
        
        # Отправка сообщений
        queue1 = console_manager.get_queue("Worker1")
        queue1.put(('stdout', 'Message 1\n'), block=False)
        queue1.put(('stdout', 'Message 2\n'), block=False)
        
        # Оба процесса используют один queue
        queue2 = console_manager.get_queue("Worker2")
        assert queue1 is queue2
        
        # Закрытие
        console_manager.close_all()
        assert len(console_manager._process_queues) == 0
    
    def test_custom_channel_workflow(self, console_manager):
        """Workflow для кастомного канала"""
        # Создание
        queue = console_manager.create_custom_channel("notifications", "Notifications")
        
        # Отправка
        queue.put(('stdout', 'Notification 1\n'), block=False)
        
        # Проверка
        retrieved_queue = console_manager.get_custom_channel_queue("notifications")
        assert retrieved_queue is queue
        
        # Регистрация в роутере
        from multiprocess_framework.modules.Router_module.router_manager import RouterManager
        router = RouterManager("test_router")
        channels = console_manager.register_in_router(router)
        
        assert "console.notifications" in channels
        
        # Отправка через роутер
        result = router.send({
            'channel': 'console.notifications',
            'text': 'Router notification',
            'level': 'INFO'
        })
        
        assert result.get('status') == 'success'


