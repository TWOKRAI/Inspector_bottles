"""
Полные тесты для CommandManager с использованием pytest.

Покрывает все сценарии использования модуля Command_module:
- Базовые операции регистрации и выполнения команд
- Работа с метаданными и тегами
- Различные стратегии диспетчеризации
- Обработка ошибок и граничных случаев
- Интеграция с ObservableMixin
- Работа со сценариями
"""
import pytest
from typing import Dict, Any, Callable
from unittest.mock import Mock, MagicMock, patch

from multiprocess_framework.modules.Command_module import CommandManager, BaseCommandManager, CommandAdapter
from multiprocess_framework.modules.Dispatch_module import DispatchStrategy


# ==================== ФИКСТУРЫ ====================

@pytest.fixture
def mock_logger_manager():
    """Мок менеджера логирования."""
    logger = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    return logger


@pytest.fixture
def mock_statistics_manager():
    """Мок менеджера статистики."""
    stats = Mock()
    stats.record_metric = Mock()
    stats.record_timing = Mock()
    stats.increment = Mock()
    stats.timing = Mock()
    return stats


@pytest.fixture
def mock_error_manager():
    """Мок менеджера ошибок."""
    error = Mock()
    error.track_error = Mock()
    error.record_error = Mock()
    return error


@pytest.fixture
def command_manager():
    """Базовый CommandManager без менеджеров."""
    return CommandManager("test_process")


@pytest.fixture
def command_manager_with_managers(mock_logger_manager, mock_statistics_manager, mock_error_manager):
    """CommandManager с подключенными менеджерами."""
    return CommandManager(
        "test_process",
        managers={
            'logger': mock_logger_manager,
            'statistics': mock_statistics_manager,
            'error': mock_error_manager
        },
        config={
            'logger': True,
            'statistics': True,
            'error': True
        }
    )


@pytest.fixture
def command_adapter(command_manager):
    """CommandAdapter с настроенным менеджером."""
    adapter = CommandAdapter(command_manager)
    adapter.setup()
    return adapter


@pytest.fixture
def sample_handler():
    """Простой обработчик команды."""
    def handler(data: Dict) -> str:
        return f"Hello, {data.get('name', 'World')}!"
    return handler


@pytest.fixture
def sample_handler_with_full_message():
    """Обработчик, ожидающий полное сообщение."""
    def handler(message: Dict) -> Dict:
        return {
            "status": "success",
            "command": message.get("command"),
            "data": message.get("data", {})
        }
    return handler


# ==================== ТЕСТЫ BaseCommandManager ====================

class TestBaseCommandManager:
    """Тесты для базового абстрактного класса."""
    
    def test_base_class_is_abstract(self):
        """Проверка что BaseCommandManager является абстрактным классом."""
        with pytest.raises(TypeError):
            BaseCommandManager("test_process")
    
    def test_base_class_has_abstract_methods(self):
        """Проверка наличия абстрактных методов."""
        assert hasattr(BaseCommandManager, 'register_command')
        assert hasattr(BaseCommandManager, 'handle_command')
        assert hasattr(BaseCommandManager, 'get_commands')


# ==================== ТЕСТЫ CommandManager - Инициализация ====================

class TestCommandManagerInitialization:
    """Тесты инициализации CommandManager."""
    
    def test_basic_initialization(self):
        """Тест базовой инициализации."""
        manager = CommandManager("my_process")
        assert manager.process_name == "my_process"
        assert manager.dispatcher is not None
        assert manager.dispatcher.name == "my_process_commands"
    
    def test_initialization_with_strategy(self):
        """Тест инициализации с указанием стратегии."""
        manager = CommandManager("test", DispatchStrategy.FALLBACK_MATCH)
        assert manager.dispatcher._default_strategy == DispatchStrategy.FALLBACK_MATCH
    
    def test_initialization_with_managers_dict(self, mock_logger_manager, mock_statistics_manager):
        """Тест инициализации с менеджерами через словарь."""
        manager = CommandManager(
            "test",
            managers={
                'logger': mock_logger_manager,
                'statistics': mock_statistics_manager
            }
        )
        assert manager.has_manager('logger')
        assert manager.has_manager('statistics')
    
    def test_initialization_backward_compatibility(self, mock_logger_manager):
        """Тест обратной совместимости со старым API."""
        manager = CommandManager(
            "test",
            logger_manager=mock_logger_manager,
            enable_logging=True
        )
        assert manager.has_manager('logger')
    
    def test_initialization_with_config(self, mock_logger_manager):
        """Тест инициализации с конфигурацией."""
        manager = CommandManager(
            "test",
            managers={'logger': mock_logger_manager},
            config={'logger': False}
        )
        assert not manager.is_enabled('logger')
    
    def test_initialization_with_config_manager(self):
        """Тест инициализации с config_manager."""
        config_mgr = Mock()
        manager = CommandManager(
            "test",
            config_manager=config_mgr
        )
        # config_manager передается в dispatcher, но не сохраняется как атрибут
        # Проверяем что менеджер создан успешно
        assert manager.dispatcher is not None
        assert manager.process_name == "test"


# ==================== ТЕСТЫ CommandManager - Регистрация команд ====================

class TestCommandManagerRegistration:
    """Тесты регистрации команд."""
    
    def test_register_simple_command(self, command_manager, sample_handler):
        """Тест регистрации простой команды."""
        result = command_manager.register_command("greet", sample_handler)
        assert result is True
        
        commands = command_manager.get_commands()
        command_names = [cmd["key"] for cmd in commands]
        assert "greet" in command_names
    
    def test_register_command_with_metadata(self, command_manager, sample_handler):
        """Тест регистрации команды с метаданными."""
        metadata = {"description": "Greeting command", "version": "1.0"}
        result = command_manager.register_command(
            "greet",
            sample_handler,
            metadata=metadata
        )
        assert result is True
        
        info = command_manager.get_command_info("greet")
        assert info is not None
        assert info["metadata"]["description"] == "Greeting command"
        assert info["metadata"]["version"] == "1.0"
    
    def test_register_command_with_tags(self, command_manager, sample_handler):
        """Тест регистрации команды с тегами."""
        result = command_manager.register_command(
            "greet",
            sample_handler,
            tags=["user", "interaction"]
        )
        assert result is True
        
        commands = command_manager.get_commands_by_tag("user")
        assert len(commands) == 1
        assert commands[0]["key"] == "greet"
    
    def test_register_command_with_efficiency(self, command_manager):
        """Тест регистрации команды с уровнем эффективности."""
        def handler(data):
            return "result"
        
        result = command_manager.register_command(
            "test",
            handler,
            efficiency=10,
            strategy=DispatchStrategy.FALLBACK_MATCH
        )
        assert result is True
    
    def test_register_command_with_strategy(self, command_manager, sample_handler):
        """Тест регистрации команды с указанием стратегии."""
        result = command_manager.register_command(
            "test",
            sample_handler,
            strategy=DispatchStrategy.PATTERN_MATCH
        )
        assert result is True
    
    def test_register_command_expects_full_message(self, command_manager, sample_handler_with_full_message):
        """Тест регистрации команды, ожидающей полное сообщение."""
        result = command_manager.register_command(
            "full",
            sample_handler_with_full_message,
            expects_full_message=True
        )
        assert result is True
        
        message = {"command": "full", "data": {"key": "value"}}
        result = command_manager.handle_command(message)
        assert result["command"] == "full"
    
    def test_register_duplicate_command(self, command_manager, sample_handler):
        """Тест регистрации дублирующейся команды."""
        command_manager.register_command("test", sample_handler)
        # Повторная регистрация должна вернуть False или перезаписать
        result = command_manager.register_command("test", sample_handler)
        # Поведение зависит от реализации диспетчера
        assert isinstance(result, bool)
    
    def test_register_command_logging(self, command_manager_with_managers, sample_handler):
        """Тест логирования при регистрации команды."""
        command_manager_with_managers.register_command("test", sample_handler)
        
        # Проверяем что были вызовы логирования
        assert command_manager_with_managers.get_manager('logger').debug.called
        assert command_manager_with_managers.get_manager('statistics').record_metric.called


# ==================== ТЕСТЫ CommandManager - Выполнение команд ====================

class TestCommandManagerExecution:
    """Тесты выполнения команд."""
    
    def test_handle_command_success(self, command_manager, sample_handler):
        """Тест успешного выполнения команды."""
        command_manager.register_command("greet", sample_handler)
        
        message = {
            "command": "greet",
            "data": {"name": "Alice"}
        }
        result = command_manager.handle_command(message)
        assert result == "Hello, Alice!"
    
    def test_handle_command_with_default_data(self, command_manager, sample_handler):
        """Тест выполнения команды с данными по умолчанию."""
        command_manager.register_command("greet", sample_handler)
        
        message = {
            "command": "greet",
            "data": {}
        }
        result = command_manager.handle_command(message)
        assert result == "Hello, World!"
    
    def test_handle_command_not_found(self, command_manager):
        """Тест обработки несуществующей команды."""
        message = {
            "command": "unknown",
            "data": {}
        }
        result = command_manager.handle_command(message)
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "No handler" in result["reason"] or "not found" in result["reason"].lower()
    
    def test_handle_command_without_command_field(self, command_manager):
        """Тест обработки сообщения без поля command."""
        message = {"data": {}}
        result = command_manager.handle_command(message)
        assert isinstance(result, dict)
        assert result["status"] == "error"
    
    def test_handle_command_with_strategy_in_message(self, command_manager):
        """Тест выполнения команды с указанием стратегии в сообщении."""
        def handler1(data):
            return "exact"
        
        def handler2(data):
            return "fallback"
        
        command_manager.register_command("test", handler1, strategy=DispatchStrategy.EXACT_MATCH)
        command_manager.register_command("test", handler2, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=10)
        
        message = {
            "command": "test",
            "strategy": "fallback",
            "data": {}
        }
        result = command_manager.handle_command(message)
        assert result == "fallback"
    
    def test_handle_command_with_exception(self, command_manager):
        """Тест обработки исключения в обработчике."""
        def failing_handler(data):
            raise ValueError("Test error")
        
        command_manager.register_command("fail", failing_handler)
        
        message = {"command": "fail", "data": {}}
        # Диспетчер перехватывает исключения и возвращает словарь с ошибкой
        result = command_manager.handle_command(message)
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "Test error" in result["reason"]
    
    def test_handle_command_logging(self, command_manager_with_managers, sample_handler):
        """Тест логирования при выполнении команды."""
        command_manager_with_managers.register_command("test", sample_handler)
        
        message = {"command": "test", "data": {}}
        command_manager_with_managers.handle_command(message)
        
        logger = command_manager_with_managers.get_manager('logger')
        assert logger.debug.called
        assert logger.info.called
    
    def test_handle_command_statistics(self, command_manager_with_managers, sample_handler):
        """Тест записи статистики при выполнении команды."""
        command_manager_with_managers.register_command("test", sample_handler)
        
        message = {"command": "test", "data": {}}
        command_manager_with_managers.handle_command(message)
        
        stats = command_manager_with_managers.get_manager('statistics')
        assert stats.record_metric.called
        assert stats.record_timing.called


# ==================== ТЕСТЫ CommandManager - Управление командами ====================

class TestCommandManagerManagement:
    """Тесты управления командами."""
    
    def test_get_commands_empty(self, command_manager):
        """Тест получения списка команд при пустом реестре."""
        commands = command_manager.get_commands()
        assert isinstance(commands, list)
    
    def test_get_commands_multiple(self, command_manager):
        """Тест получения списка нескольких команд."""
        def handler1(data):
            return "1"
        
        def handler2(data):
            return "2"
        
        command_manager.register_command("cmd1", handler1)
        command_manager.register_command("cmd2", handler2)
        
        commands = command_manager.get_commands()
        assert len(commands) >= 2
        
        command_names = [cmd["key"] for cmd in commands]
        assert "cmd1" in command_names
        assert "cmd2" in command_names
    
    def test_get_command_info_existing(self, command_manager, sample_handler):
        """Тест получения информации о существующей команде."""
        metadata = {"description": "Test command"}
        command_manager.register_command("test", sample_handler, metadata=metadata)
        
        info = command_manager.get_command_info("test")
        assert info is not None
        assert info["key"] == "test"
        assert info["metadata"]["description"] == "Test command"
    
    def test_get_command_info_not_found(self, command_manager):
        """Тест получения информации о несуществующей команде."""
        info = command_manager.get_command_info("nonexistent")
        assert info is None
    
    def test_get_commands_by_tag(self, command_manager):
        """Тест получения команд по тегу."""
        def handler1(data):
            return "1"
        
        def handler2(data):
            return "2"
        
        def handler3(data):
            return "3"
        
        command_manager.register_command("cmd1", handler1, tags=["group1"])
        command_manager.register_command("cmd2", handler2, tags=["group1", "group2"])
        command_manager.register_command("cmd3", handler3, tags=["group2"])
        
        group1_commands = command_manager.get_commands_by_tag("group1")
        assert len(group1_commands) == 2
        
        group2_commands = command_manager.get_commands_by_tag("group2")
        assert len(group2_commands) == 2
    
    def test_get_commands_by_tag_empty(self, command_manager):
        """Тест получения команд по несуществующему тегу."""
        commands = command_manager.get_commands_by_tag("nonexistent")
        assert isinstance(commands, list)
        assert len(commands) == 0
    
    def test_update_command_metadata(self, command_manager, sample_handler):
        """Тест обновления метаданных команды."""
        command_manager.register_command("test", sample_handler, metadata={"old": "value"})
        
        new_metadata = {"new": "value", "description": "Updated"}
        result = command_manager.update_command_metadata("test", new_metadata)
        assert result is True
        
        info = command_manager.get_command_info("test")
        assert info["metadata"]["new"] == "value"
        assert info["metadata"]["description"] == "Updated"
    
    def test_update_command_metadata_not_found(self, command_manager):
        """Тест обновления метаданных несуществующей команды."""
        result = command_manager.update_command_metadata("nonexistent", {})
        assert result is False
    
    def test_update_command_tags(self, command_manager, sample_handler):
        """Тест обновления тегов команды."""
        command_manager.register_command("test", sample_handler, tags=["tag1"])
        
        result = command_manager.update_command_tags("test", ["tag2", "tag3"])
        assert result is True
        
        commands = command_manager.get_commands_by_tag("tag2")
        assert len(commands) == 1
        assert commands[0]["key"] == "test"
    
    def test_update_command_tags_not_found(self, command_manager):
        """Тест обновления тегов несуществующей команды."""
        result = command_manager.update_command_tags("nonexistent", [])
        assert result is False
    
    def test_overwrite_command(self, command_manager):
        """Тест перезаписи команды."""
        def old_handler(data):
            return "old"
        
        def new_handler(data):
            return "new"
        
        command_manager.register_command("test", old_handler)
        
        result = command_manager.overwrite_command("test", new_handler)
        assert result is True
        
        message = {"command": "test", "data": {}}
        response = command_manager.handle_command(message)
        assert response == "new"
    
    def test_overwrite_command_not_found(self, command_manager):
        """Тест перезаписи несуществующей команды."""
        def handler(data):
            return "new"
        
        result = command_manager.overwrite_command("nonexistent", handler)
        # Может вернуть True (создать новую) или False (не найдена)
        assert isinstance(result, bool)


# ==================== ТЕСТЫ CommandManager - Статистика ====================

class TestCommandManagerStatistics:
    """Тесты статистики CommandManager."""
    
    def test_get_stats_empty(self, command_manager):
        """Тест получения статистики при пустом реестре."""
        stats = command_manager.get_stats()
        assert stats["process_name"] == "test_process"
        assert stats["total_commands"] == 0
        assert isinstance(stats["commands"], list)
    
    def test_get_stats_with_commands(self, command_manager):
        """Тест получения статистики с командами."""
        def handler1(data):
            return "1"
        
        def handler2(data):
            return "2"
        
        command_manager.register_command("cmd1", handler1)
        command_manager.register_command("cmd2", handler2)
        
        stats = command_manager.get_stats()
        assert stats["total_commands"] >= 2
        assert "cmd1" in stats["commands"]
        assert "cmd2" in stats["commands"]


# ==================== ТЕСТЫ CommandManager - Сценарии ====================

class TestCommandManagerScenarios:
    """Тесты работы со сценариями."""
    
    def test_handle_command_with_scenario(self, command_manager):
        """Тест выполнения команды через сценарий."""
        def step1(data):
            value = data.get("value", 0) if isinstance(data, dict) else data
            return {"step": 1, "value": value + 1}
        
        def step2(data):
            value = data.get("value", 0) if isinstance(data, dict) else data
            return {"step": 2, "value": value * 2}
        
        # Создаем сценарий
        command_manager.dispatcher.create_scenario("process", "Test scenario")
        command_manager.dispatcher.add_handler_to_scenario("process", "step1", step1, stage=1)
        command_manager.dispatcher.add_handler_to_scenario("process", "step2", step2, stage=2)
        
        # Выполняем сценарий через команду
        message = {
            "command": "process",
            "data": {"value": 5}
        }
        
        result = command_manager.handle_command(message)
        assert isinstance(result, dict)
        assert result["status"] == "success"
        assert result["scenario"] == "process"
        assert len(result["stages"]) == 2
        assert result["stages"][1]["result"]["value"] == 12  # (5+1)*2


# ==================== ТЕСТЫ CommandManager - Стратегии ====================

class TestCommandManagerStrategies:
    """Тесты работы с различными стратегиями."""
    
    def test_multiple_strategies_same_key(self, command_manager):
        """Тест работы с несколькими стратегиями для одного ключа."""
        def exact_handler(data):
            return "exact"
        
        def fallback_handler(data):
            return "fallback"
        
        command_manager.register_command("test", exact_handler, strategy=DispatchStrategy.EXACT_MATCH)
        command_manager.register_command("test", fallback_handler, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=5)
        
        # По умолчанию используется EXACT_MATCH
        message = {"command": "test", "data": {}}
        result = command_manager.handle_command(message)
        assert result == "exact"
        
        # Явно указываем fallback
        message["strategy"] = "fallback"
        result = command_manager.handle_command(message)
        assert result == "fallback"
    
    def test_pattern_match_strategy(self, command_manager):
        """Тест работы со стратегией PATTERN_MATCH."""
        def handler(data):
            return "matched"
        
        command_manager.register_command(
            r"test.*",
            handler,
            strategy=DispatchStrategy.PATTERN_MATCH
        )
        
        message = {"command": "test123", "data": {}}
        result = command_manager.handle_command(message)
        assert result == "matched"


# ==================== ТЕСТЫ CommandManager - ObservableMixin ====================

class TestCommandManagerObservableMixin:
    """Тесты интеграции с ObservableMixin."""
    
    def test_logging_context(self, command_manager_with_managers, sample_handler):
        """Тест использования контекста логирования."""
        command_manager_with_managers.register_command("test", sample_handler)
        
        # Временно отключаем логирование
        with command_manager_with_managers.context('logger', enabled=False):
            assert not command_manager_with_managers.is_enabled('logger')
        
        # После выхода из контекста должно быть включено
        assert command_manager_with_managers.is_enabled('logger')
    
    def test_enable_disable_managers(self, command_manager_with_managers):
        """Тест включения/выключения менеджеров."""
        command_manager_with_managers.disable('logger')
        assert not command_manager_with_managers.is_enabled('logger')
        
        command_manager_with_managers.enable('logger')
        assert command_manager_with_managers.is_enabled('logger')
    
    def test_get_enabled_managers(self, command_manager_with_managers):
        """Тест получения списка включенных менеджеров."""
        enabled = command_manager_with_managers.get_enabled_managers()
        assert 'logger' in enabled
        assert 'statistics' in enabled


# ==================== ТЕСТЫ CommandAdapter ====================

class TestCommandAdapter:
    """Тесты для CommandAdapter."""
    
    def test_adapter_initialization(self, command_manager):
        """Тест инициализации адаптера."""
        adapter = CommandAdapter(command_manager)
        assert adapter.manager == command_manager
        assert adapter.adapter_name == "CommandAdapter"
    
    def test_adapter_setup(self, command_manager):
        """Тест настройки адаптера."""
        adapter = CommandAdapter(command_manager)
        result = adapter.setup()
        assert result is True
        assert adapter.is_initialized()
    
    def test_adapter_setup_without_manager(self):
        """Тест настройки адаптера без менеджера."""
        adapter = CommandAdapter(None)
        result = adapter.setup()
        assert result is False
    
    def test_adapter_register_command(self, command_adapter, sample_handler):
        """Тест регистрации команды через адаптер."""
        result = command_adapter.register("test", sample_handler)
        assert result is True
        assert command_adapter.has_command("test")
    
    def test_adapter_register_with_metadata(self, command_adapter, sample_handler):
        """Тест регистрации команды с метаданными через адаптер."""
        metadata = {"description": "Test command"}
        result = command_adapter.register("test", sample_handler, metadata=metadata)
        assert result is True
        
        info = command_adapter.get_command_info("test")
        assert info["metadata"]["description"] == "Test command"
    
    def test_adapter_unregister(self, command_adapter, sample_handler):
        """Тест отмены регистрации команды."""
        command_adapter.register("test", sample_handler)
        assert command_adapter.has_command("test")
        
        result = command_adapter.unregister("test")
        assert result is True
        assert not command_adapter.has_command("test")
    
    def test_adapter_unregister_not_found(self, command_adapter):
        """Тест отмены регистрации несуществующей команды."""
        result = command_adapter.unregister("nonexistent")
        assert result is False
    
    def test_adapter_execute(self, command_adapter, sample_handler):
        """Тест прямого выполнения команды через адаптер."""
        command_adapter.register("greet", sample_handler)
        
        result = command_adapter.execute("greet", {"name": "Bob"})
        assert result == "Hello, Bob!"
    
    def test_adapter_execute_not_found(self, command_adapter):
        """Тест выполнения несуществующей команды."""
        result = command_adapter.execute("nonexistent", {})
        assert isinstance(result, dict)
        assert result["status"] == "error"
    
    def test_adapter_execute_with_exception(self, command_adapter):
        """Тест выполнения команды с исключением."""
        def failing_handler(data):
            raise RuntimeError("Test error")
        
        command_adapter.register("fail", failing_handler)
        
        result = command_adapter.execute("fail", {})
        assert result["status"] == "error"
        assert "Test error" in result["reason"]
    
    def test_adapter_execute_via_message(self, command_adapter):
        """Тест выполнения команды через систему сообщений."""
        # Создаем мок процесса с message_manager
        mock_process = Mock()
        mock_message_manager = Mock()
        mock_message = Mock()
        mock_message.to_dict.return_value = {"command": "test"}
        
        mock_message_manager.create_command_message.return_value = mock_message
        mock_process.message_manager = mock_message_manager
        mock_process.router = Mock()
        mock_process.router.send.return_value = {"status": "success"}
        
        command_adapter.process = mock_process
        
        result = command_adapter.execute_via_message("test", {}, ["target1"], need_ack=True)
        assert result is True
        mock_message_manager.create_command_message.assert_called_once()
    
    def test_adapter_execute_via_message_no_process(self, command_adapter):
        """Тест выполнения команды через сообщения без процесса."""
        result = command_adapter.execute_via_message("test", {}, ["target1"])
        assert result is False
    
    def test_adapter_list_commands(self, command_adapter, sample_handler):
        """Тест получения списка команд через адаптер."""
        command_adapter.register("cmd1", sample_handler)
        command_adapter.register("cmd2", sample_handler)
        
        commands = command_adapter.list_commands()
        assert isinstance(commands, list)
        assert len(commands) >= 2
    
    def test_adapter_list_commands_empty(self, command_adapter):
        """Тест получения пустого списка команд."""
        commands = command_adapter.list_commands()
        assert isinstance(commands, list)
    
    def test_adapter_has_command(self, command_adapter, sample_handler):
        """Тест проверки наличия команды."""
        assert not command_adapter.has_command("test")
        
        command_adapter.register("test", sample_handler)
        assert command_adapter.has_command("test")
    
    def test_adapter_get_command_info(self, command_adapter, sample_handler):
        """Тест получения информации о команде через адаптер."""
        metadata = {"description": "Test"}
        command_adapter.register("test", sample_handler, metadata=metadata)
        
        info = command_adapter.get_command_info("test")
        assert info is not None
        assert info["metadata"]["description"] == "Test"
    
    def test_adapter_get_command_info_not_found(self, command_adapter):
        """Тест получения информации о несуществующей команде."""
        info = command_adapter.get_command_info("nonexistent")
        assert info is None
    
    def test_adapter_get_stats(self, command_adapter, sample_handler):
        """Тест получения статистики адаптера."""
        command_adapter.register("cmd1", sample_handler)
        command_adapter.register("cmd2", sample_handler)
        
        stats = command_adapter.get_stats()
        # Адаптер регистрирует базовые команды при setup (get_stats, list_commands)
        # Поэтому общее количество команд будет больше
        assert stats["total_commands"] >= 2
        assert "cmd1" in stats["commands"]
        assert "cmd2" in stats["commands"]
        # Проверяем что базовые команды тоже есть
        assert "get_stats" in stats["commands"]
        assert "list_commands" in stats["commands"]
    
    def test_adapter_base_commands_registered(self, command_adapter):
        """Тест что базовые команды зарегистрированы при setup."""
        assert command_adapter.has_command("get_stats")
        assert command_adapter.has_command("list_commands")
    
    def test_adapter_base_command_get_stats(self, command_adapter):
        """Тест выполнения базовой команды get_stats."""
        result = command_adapter.execute("get_stats", {})
        assert isinstance(result, dict)
        assert "total_commands" in result
    
    def test_adapter_base_command_list_commands(self, command_adapter):
        """Тест выполнения базовой команды list_commands."""
        result = command_adapter.execute("list_commands", {})
        assert isinstance(result, list)


# ==================== ТЕСТЫ Граничных случаев ====================

class TestEdgeCases:
    """Тесты граничных случаев и обработки ошибок."""
    
    def test_empty_message(self, command_manager):
        """Тест обработки пустого сообщения."""
        result = command_manager.handle_command({})
        assert isinstance(result, dict)
        assert result["status"] == "error"
    
    def test_message_with_none_data(self, command_manager, sample_handler):
        """Тест обработки сообщения с None в данных."""
        command_manager.register_command("test", sample_handler)
        
        message = {"command": "test", "data": None}
        # Когда data=None, диспетчер передает None в обработчик
        # Обработчик пытается вызвать .get() на None, что вызывает ошибку
        # Диспетчер перехватывает ошибку и возвращает словарь с ошибкой
        result = command_manager.handle_command(message)
        # Результат будет словарем с ошибкой, так как обработчик не может обработать None
        assert isinstance(result, dict)
        assert result["status"] == "error"
    
    def test_handler_returning_none(self, command_manager):
        """Тест обработчика, возвращающего None."""
        def handler(data):
            return None
        
        command_manager.register_command("test", handler)
        message = {"command": "test", "data": {}}
        result = command_manager.handle_command(message)
        assert result is None
    
    def test_handler_with_complex_data(self, command_manager):
        """Тест обработчика со сложными данными."""
        def handler(data):
            return {
                "received": data,
                "processed": True
            }
        
        command_manager.register_command("test", handler)
        
        complex_data = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "number": 42
        }
        
        message = {"command": "test", "data": complex_data}
        result = command_manager.handle_command(message)
        assert result["received"] == complex_data
        assert result["processed"] is True
    
    def test_multiple_tags_same_command(self, command_manager, sample_handler):
        """Тест команды с несколькими тегами."""
        command_manager.register_command(
            "test",
            sample_handler,
            tags=["tag1", "tag2", "tag3"]
        )
        
        for tag in ["tag1", "tag2", "tag3"]:
            commands = command_manager.get_commands_by_tag(tag)
            assert len(commands) == 1
            assert commands[0]["key"] == "test"
    
    def test_empty_tags(self, command_manager, sample_handler):
        """Тест регистрации команды с пустым списком тегов."""
        result = command_manager.register_command("test", sample_handler, tags=[])
        assert result is True
        
        commands = command_manager.get_commands_by_tag("any_tag")
        # Команда не должна быть найдена по тегу
        assert "test" not in [cmd["key"] for cmd in commands]


# ==================== ТЕСТЫ Производительности ====================

class TestPerformance:
    """Тесты производительности (базовые проверки)."""
    
    def test_register_many_commands(self, command_manager):
        """Тест регистрации большого количества команд."""
        def make_handler(i):
            def handler(data):
                return f"result_{i}"
            return handler
        
        for i in range(100):
            command_manager.register_command(f"cmd_{i}", make_handler(i))
        
        commands = command_manager.get_commands()
        assert len(commands) >= 100
    
    def test_execute_many_commands(self, command_manager):
        """Тест выполнения большого количества команд."""
        def handler(data):
            return "ok"
        
        for i in range(50):
            command_manager.register_command(f"cmd_{i}", handler)
        
        for i in range(50):
            message = {"command": f"cmd_{i}", "data": {}}
            result = command_manager.handle_command(message)
            assert result == "ok"


# ==================== ТЕСТЫ Интеграции ====================

class TestIntegration:
    """Интеграционные тесты."""
    
    def test_full_workflow(self, command_manager):
        """Тест полного рабочего процесса."""
        # Регистрация
        def process_handler(data):
            return {"processed": data.get("value", 0) * 2}
        
        command_manager.register_command(
            "process",
            process_handler,
            metadata={"version": "1.0"},
            tags=["processing"]
        )
        
        # Выполнение
        message = {"command": "process", "data": {"value": 5}}
        result = command_manager.handle_command(message)
        assert result["processed"] == 10
        
        # Получение информации
        info = command_manager.get_command_info("process")
        assert info["metadata"]["version"] == "1.0"
        
        # Обновление метаданных
        command_manager.update_command_metadata("process", {"version": "2.0"})
        info = command_manager.get_command_info("process")
        assert info["metadata"]["version"] == "2.0"
        
        # Получение по тегу
        commands = command_manager.get_commands_by_tag("processing")
        assert len(commands) == 1
        
        # Статистика
        stats = command_manager.get_stats()
        assert stats["total_commands"] >= 1
    
    def test_adapter_full_workflow(self, command_adapter):
        """Тест полного рабочего процесса через адаптер."""
        def handler(data):
            return f"Processed: {data.get('input', '')}"
        
        # Регистрация
        command_adapter.register("process", handler)
        
        # Выполнение
        result = command_adapter.execute("process", {"input": "test"})
        assert result == "Processed: test"
        
        # Проверка наличия
        assert command_adapter.has_command("process")
        
        # Получение информации
        info = command_adapter.get_command_info("process")
        assert info is not None
        
        # Список команд
        commands = command_adapter.list_commands()
        assert len(commands) >= 1
        
        # Статистика
        stats = command_adapter.get_stats()
        assert stats["total_commands"] >= 1

