"""
Тесты для модуля message.py

Проверяем корректность работы основного класса Message.
"""
import pytest
import json
import time
from multiprocess_framework.modules.Message_module.message import Message, MessageValidationError, create_message, parse_message
from multiprocess_framework.modules.Message_module.message_types import MessageType, Priority, LogLevel


class TestMessageCreation:
    """Тесты создания сообщений."""
    
    def test_create_basic_message(self):
        """Проверяем создание базового сообщения."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test_sender",
            targets=["target1", "target2"]
        )
        
        assert msg.type == "general"
        assert msg.sender == "test_sender"
        assert msg.targets == ["target1", "target2"]
        assert isinstance(msg.id, str)
        assert isinstance(msg.timestamp, float)
        assert msg.id.startswith("gen_")
        
    def test_create_with_string_type(self):
        """Проверяем создание сообщения со строковым типом."""
        msg = Message.create(
            type="command",
            sender="sender",
            targets=["target"]
        )
        
        assert msg.type == "command"
        assert msg.id.startswith("cmd_")
        
    def test_create_different_types(self):
        """Проверяем создание разных типов сообщений."""
        # COMMAND
        cmd_msg = Message.create(
            type=MessageType.COMMAND,
            sender="gui",
            targets=["worker"],
            command="process",
            args={"file": "test.txt"}
        )
        assert cmd_msg.command == "process"
        assert cmd_msg.args == {"file": "test.txt"}
        
        # LOG - используем строки вместо enum для прямого создания
        log_msg = Message.create(
            type=MessageType.LOG,
            sender="module",
            targets=["logger"],
            level="info",  # Используем строку вместо LogLevel.INFO
            message="Test log message"
        )
        assert log_msg.level == "info"  # Теперь это строка
        assert log_msg.message == "Test log message"
        
        # REQUEST
        req_msg = Message.create(
            type=MessageType.REQUEST,
            sender="client",
            targets=["server"],
            request_type="get_data",
            query={"id": 123}
        )
        assert req_msg.request_type == "get_data"
        assert req_msg.query == {"id": 123}
        
    def test_apply_type_defaults(self):
        """Проверяем применение дефолтных значений для типов."""
        # LOG сообщение должно получить дефолтные targets и routers
        log_msg = Message.create(
            type=MessageType.LOG,
            sender="test",
            level="info",
            message="test"
        )
        assert log_msg.targets == ["logger"]
        assert log_msg.routers == ["log"]
        assert log_msg.channel == "log"
        
        # BROADCAST сообщение должно получить дефолтные targets
        broadcast_msg = Message.create(
            type=MessageType.BROADCAST,
            sender="test",
            content="hello"
        )
        assert broadcast_msg.targets == ["all"]
        assert broadcast_msg.channel == "broadcast"


class TestFluentAPI:
    """Тесты для Fluent API."""
    
    def test_priority_setting(self):
        """Проверяем установку приоритета."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        ).set_priority(Priority.HIGH)
        
        assert msg.priority == "high"
        
    def test_targets_management(self):
        """Проверяем управление получателями."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target1"]
        )
        
        msg.add_target("target2")
        assert msg.targets == ["target1", "target2"]
        
        msg.set_targets(["target3", "target4"])
        assert msg.targets == ["target3", "target4"]
    
    def test_add_target_duplicate(self):
        """Проверяем, что add_target не добавляет дубликаты."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target1"]
        )
        
        msg.add_target("target1")  # Пытаемся добавить существующий
        assert msg.targets == ["target1"]  # Дубликат не должен быть добавлен
        
        msg.add_target("target2")
        assert msg.targets == ["target1", "target2"]
    
    def test_add_router_duplicate(self):
        """Проверяем, что add_router не добавляет дубликаты."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        )
        
        msg.add_router("router1")
        assert msg.routers == ["internal", "router1"]
        
        msg.add_router("router1")  # Пытаемся добавить существующий
        assert msg.routers == ["internal", "router1"]  # Дубликат не должен быть добавлен
        
    def test_command_setting(self):
        """Проверяем установку команды."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="test",
            targets=["worker"]
        ).set_command("process", {"file": "test.txt"})
        
        assert msg.command == "process"
        assert msg.args == {"file": "test.txt"}
    
    def test_command_setting_without_args(self):
        """Проверяем установку команды без аргументов."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="test",
            targets=["worker"]
        ).set_command("process")
        
        assert msg.command == "process"
        assert msg.args == {}  # Должны быть пустые args по умолчанию
    
    def test_set_args(self):
        """Проверяем установку аргументов команды."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="test",
            targets=["worker"],
            command="process"
        )
        
        msg.set_args({"param1": "value1", "param2": 123})
        assert msg.args == {"param1": "value1", "param2": 123}
    
    def test_add_arg(self):
        """Проверяем добавление аргумента команды."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="test",
            targets=["worker"],
            command="process"
        )
        
        msg.add_arg("param1", "value1")
        msg.add_arg("param2", 123)
        
        assert msg.args == {"param1": "value1", "param2": 123}
        
    def test_log_setting(self):
        """Проверяем установку параметров лога."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="module",
            targets=["logger"]
        ).set_log(LogLevel.ERROR, "Error occurred", "database")
        
        assert msg.level == "error"  # enum конвертируется в строку
        assert msg.message == "Error occurred"
        assert msg.module == "database"
    
    def test_log_setting_with_string_level(self):
        """Проверяем установку лога со строковым уровнем."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="module",
            targets=["logger"]
        ).set_log("warning", "Warning message")
        
        assert msg.level == "warning"
        assert msg.message == "Warning message"
        assert msg.module == "main"  # Дефолтное значение
    
    def test_set_system_action(self):
        """Проверяем установку системного действия."""
        msg = Message.create(
            type=MessageType.SYSTEM,
            sender="ProcessManager",
            targets=["all"]
        ).set_system_action("shutdown", {"reason": "user_request"})
        
        assert msg.action == "shutdown"
        assert msg.data == {"reason": "user_request"}
    
    def test_set_system_action_without_data(self):
        """Проверяем установку системного действия без данных."""
        msg = Message.create(
            type=MessageType.SYSTEM,
            sender="ProcessManager",
            targets=["all"]
        ).set_system_action("restart")
        
        assert msg.action == "restart"
        assert msg.data is None
    
    def test_set_data(self):
        """Проверяем установку данных."""
        msg = Message.create(
            type=MessageType.DATA,
            sender="producer",
            targets=["consumer"]
        ).set_data(b"binary_data", "image")
        
        assert msg.data == b"binary_data"
        assert msg.data_type == "image"
    
    def test_set_data_without_type(self):
        """Проверяем установку данных без типа."""
        msg = Message.create(
            type=MessageType.DATA,
            sender="producer",
            targets=["consumer"]
        ).set_data({"key": "value"})
        
        assert msg.data == {"key": "value"}
        assert msg.data_type is None
    
    def test_set_event(self):
        """Проверяем установку события."""
        msg = Message.create(
            type=MessageType.EVENT,
            sender="Camera"
        ).set_event("frame_captured", {"frame_id": 999})
        
        assert msg.event_type == "frame_captured"
        assert msg.event_data == {"frame_id": 999}
    
    def test_set_event_without_data(self):
        """Проверяем установку события без данных."""
        msg = Message.create(
            type=MessageType.EVENT,
            sender="Camera"
        ).set_event("shutdown")
        
        assert msg.event_type == "shutdown"
        assert msg.event_data is None
        
    def test_metadata_management(self):
        """Проверяем управление метаданными."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        )
        
        msg.add_metadata("user_id", 12345)
        msg.add_metadata("session_id", "abc123")
        
        assert msg.metadata == {
            "user_id": 12345,
            "session_id": "abc123"
        }
        
        msg.set_metadata({"new_key": "new_value"})
        assert msg.metadata == {"new_key": "new_value"}


class TestMessageValidation:
    """Тесты валидации сообщений."""
    
    def test_valid_message(self):
        """Проверяем валидное сообщение."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content="Hello"
        )
        
        assert msg.validate() == True
        assert msg.is_valid() == True
        
    def test_invalid_no_sender(self):
        """Проверяем сообщение без отправителя."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="",  # Пустой отправитель
            targets=["target"]
        )
        
        with pytest.raises(MessageValidationError):
            msg.validate()
        assert msg.is_valid() == False
        
    def test_invalid_no_targets(self):
        """Проверяем сообщение без получателей."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=[]  # Пустой список получателей
        )
        
        with pytest.raises(MessageValidationError):
            msg.validate()
        assert msg.is_valid() == False
        
    def test_invalid_log_no_level(self):
        """Проверяем LOG сообщение без уровня."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="test",
            targets=["logger"],
            message="test message"
            # Нет level - должно быть ошибкой
        )
        
        with pytest.raises(MessageValidationError):
            msg.validate()
            
    def test_invalid_command_no_command(self):
        """Проверяем COMMAND сообщение без команды."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="test",
            targets=["worker"]
            # Нет command - должно быть ошибкой
        )
        
        with pytest.raises(MessageValidationError):
            msg.validate()


class TestMessageConversion:
    """Тесты конвертации сообщений."""
    
    def test_to_dict_basic(self):
        """Проверяем конвертацию в словарь."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content="Hello world"
        )
        
        data = msg.to_dict()
        
        assert data["type"] == "general"
        assert data["sender"] == "test"
        assert data["targets"] == ["target"]
        assert data["content"] == "Hello world"
        assert "id" in data
        assert "timestamp" in data
        
    def test_to_dict_exclude_none(self):
        """Проверяем исключение None полей."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        )
        
        data = msg.to_dict(exclude_none=True)
        # Поле content должно быть исключено, т.к. оно None
        assert "content" not in data
        
        data_with_none = msg.to_dict(exclude_none=False)
        # Поле content должно быть включено, даже если None
        assert "content" in data_with_none
        assert data_with_none["content"] is None
        
    def test_to_json(self):
        """Проверяем конвертацию в JSON."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content={"key": "value"}
        )
        
        json_str = msg.to_json()
        data = json.loads(json_str)
        
        assert data["type"] == "general"
        assert data["sender"] == "test"
        assert data["content"] == {"key": "value"}
        
    def test_to_text(self):
        """Проверяем конвертацию в текстовый формат."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content="Hello"
        )
        
        text = msg.to_text()
        assert "type: general" in text
        assert "sender: test" in text
        assert "targets: [\"target\"]" in text
        assert "content: Hello" in text
    
    def test_to_yaml(self):
        """Проверяем конвертацию в YAML."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML не установлен")
        
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="test",
            targets=["target"],
            command="process",
            args={"file": "test.txt"}
        )
        
        yaml_str = msg.to_yaml()
        assert isinstance(yaml_str, str)
        assert "type: command" in yaml_str or "type: 'command'" in yaml_str
        assert "sender: test" in yaml_str or "sender: 'test'" in yaml_str
        assert "command: process" in yaml_str or "command: 'process'" in yaml_str
        
        # Проверяем, что можно распарсить обратно
        parsed = yaml.safe_load(yaml_str)
        assert parsed["type"] == "command"
        assert parsed["command"] == "process"
    
    def test_to_yaml_without_pyyaml(self):
        """Проверяем, что to_yaml выбрасывает ImportError если PyYAML не установлен."""
        # Мокаем отсутствие PyYAML
        import sys
        original_yaml = sys.modules.get('yaml')
        if 'yaml' in sys.modules:
            del sys.modules['yaml']
        
        # Временно заменяем YAML_AVAILABLE
        from multiprocess_framework.modules.Message_module import message
        original_yaml_available = message.YAML_AVAILABLE
        message.YAML_AVAILABLE = False
        
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        )
        
        with pytest.raises(ImportError, match="PyYAML is not installed"):
            msg.to_yaml()
        
        # Восстанавливаем
        message.YAML_AVAILABLE = original_yaml_available
        if original_yaml:
            sys.modules['yaml'] = original_yaml
    
    def test_to_dict_exclude_fields(self):
        """Проверяем исключение полей при конвертации в словарь."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="test",
            targets=["logger"],
            level="info",
            message="test message"
        )
        
        # LOG сообщения должны исключать routers
        data = msg.to_dict()
        assert "routers" not in data
        
        # Но должны быть другие поля
        assert "type" in data
        assert "level" in data
        assert "message" in data
    
    def test_to_dict_include_fields(self):
        """Проверяем включение только определенных полей."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content="Hello"
        )
        
        data = msg.to_dict(include_fields={"type", "sender", "targets"})
        assert set(data.keys()) == {"type", "sender", "targets"}
        assert data["type"] == "general"
        assert data["sender"] == "test"
        assert data["targets"] == ["target"]


class TestMessageParsing:
    """Тесты парсинга сообщений."""
    
    def test_from_dict(self):
        """Проверяем создание сообщения из словаря."""
        original_msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content="Hello"
        )
        
        data = original_msg.to_dict()
        parsed_msg = Message.from_dict(data)
        
        assert parsed_msg.type == original_msg.type
        assert parsed_msg.sender == original_msg.sender
        assert parsed_msg.targets == original_msg.targets
        assert parsed_msg.content == original_msg.content
        
    def test_from_json(self):
        """Проверяем создание сообщения из JSON."""
        original_msg = Message.create(
            type=MessageType.COMMAND,
            sender="gui",
            targets=["worker"],
            command="process",
            args={"file": "test.txt"}
        )
        
        json_str = original_msg.to_json()
        parsed_msg = Message.from_json(json_str)
        
        assert parsed_msg.type == "command"
        assert parsed_msg.command == "process"
        assert parsed_msg.args == {"file": "test.txt"}
        
    def test_parse_message_function_dict(self):
        """Проверяем функцию parse_message со словарем."""
        data = {
            "type": "general",
            "sender": "test",
            "targets": ["target"],
            "content": "Hello"
        }
        
        msg = parse_message(data)
        assert isinstance(msg, Message)
        assert msg.type == "general"
        assert msg.sender == "test"
        
    def test_parse_message_function_json(self):
        """Проверяем функцию parse_message с JSON строкой."""
        data = {
            "type": "event",
            "sender": "system",
            "targets": ["all"],
            "event_type": "shutdown"
        }
        
        json_str = json.dumps(data)
        msg = parse_message(json_str)
        
        assert isinstance(msg, Message)
        assert msg.type == "event"
        assert msg.event_type == "shutdown"
    
    def test_from_yaml(self):
        """Проверяем создание сообщения из YAML."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML не установлен")
        
        yaml_str = """
type: command
sender: test_sender
targets:
  - target1
  - target2
command: process
args:
  file: test.txt
priority: high
"""
        
        msg = Message.from_yaml(yaml_str)
        assert isinstance(msg, Message)
        assert msg.type == "command"
        assert msg.sender == "test_sender"
        assert msg.targets == ["target1", "target2"]
        assert msg.command == "process"
        assert msg.args == {"file": "test.txt"}
        assert msg.priority == "high"
    
    def test_from_yaml_without_pyyaml(self):
        """Проверяем, что from_yaml выбрасывает ImportError если PyYAML не установлен."""
        # Мокаем отсутствие PyYAML
        import sys
        original_yaml = sys.modules.get('yaml')
        if 'yaml' in sys.modules:
            del sys.modules['yaml']
        
        # Временно заменяем YAML_AVAILABLE
        from multiprocess_framework.modules.Message_module import message
        original_yaml_available = message.YAML_AVAILABLE
        message.YAML_AVAILABLE = False
        
        yaml_str = "type: general\nsender: test"
        
        with pytest.raises(ImportError, match="PyYAML is not installed"):
            Message.from_yaml(yaml_str)
        
        # Восстанавливаем
        message.YAML_AVAILABLE = original_yaml_available
        if original_yaml:
            sys.modules['yaml'] = original_yaml
    
    def test_parse_message_function_yaml(self):
        """Проверяем функцию parse_message с YAML строкой."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML не установлен")
        
        yaml_str = """
type: general
sender: test
targets:
  - target1
content: Hello World
"""
        
        msg = parse_message(yaml_str)
        assert isinstance(msg, Message)
        assert msg.type == "general"
        assert msg.sender == "test"
        assert msg.content == "Hello World"
    
    def test_parse_message_invalid_format(self):
        """Проверяем, что parse_message выбрасывает ошибку для невалидного формата."""
        invalid_data = "это не JSON и не YAML и не dict"
        
        with pytest.raises(ValueError, match="Unable to parse message"):
            parse_message(invalid_data)


class TestMessageHelpers:
    """Тесты вспомогательных методов."""
    
    def test_get_type_enum(self):
        """Проверяем получение типа как enum."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="test",
            targets=["logger"],
            level="info",
            message="test"
        )
        
        msg_type = msg.get_type()
        assert msg_type == MessageType.LOG
    
    def test_get_type_invalid(self):
        """Проверяем получение типа для невалидного типа."""
        msg = Message.create(
            type="invalid_type",
            sender="test",
            targets=["target"]
        )
        
        msg_type = msg.get_type()
        assert msg_type is None  # Должен вернуть None для невалидного типа
    
    def test_get_priority_invalid(self):
        """Проверяем получение приоритета для невалидного значения."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        )
        msg.priority = "invalid_priority"
        
        priority = msg.get_priority()
        assert priority == Priority.NORMAL  # Должен вернуть дефолтный приоритет
    
    def test_get_log_level_invalid(self):
        """Проверяем получение уровня лога для невалидного значения."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="test",
            targets=["logger"],
            level="invalid_level",
            message="test"
        )
        
        log_level = msg.get_log_level()
        assert log_level is None  # Должен вернуть None для невалидного уровня
    
    def test_get_log_level_none(self):
        """Проверяем получение уровня лога когда level не установлен."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        )
        
        log_level = msg.get_log_level()
        assert log_level is None  # Должен вернуть None если level не установлен
        
    def test_get_priority_enum(self):
        """Проверяем получение приоритета как enum."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"]
        ).set_priority(Priority.URGENT)
        
        priority = msg.get_priority()
        assert priority == Priority.URGENT
        
    def test_get_log_level_enum(self):
        """Проверяем получение уровня лога как enum."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="test",
            targets=["logger"],
            level="warning",
            message="test"
        )
        
        log_level = msg.get_log_level()
        assert log_level == LogLevel.WARNING
        
    def test_clone_message(self):
        """Проверяем клонирование сообщения."""
        original_msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content="Hello",
            metadata={"key": "value"}
        )
        
        # Добавляем небольшую задержку, чтобы timestamp гарантированно отличался
        time.sleep(0.001)
        cloned_msg = original_msg.clone()
        
        # Содержимое должно совпадать
        assert cloned_msg.type == original_msg.type
        assert cloned_msg.sender == original_msg.sender
        assert cloned_msg.targets == original_msg.targets
        assert cloned_msg.content == original_msg.content
        assert cloned_msg.metadata == original_msg.metadata
        
        # Но ID и timestamp должны быть разными
        assert cloned_msg.id != original_msg.id
        assert cloned_msg.timestamp != original_msg.timestamp
        
        # Проверяем, что timestamp клона больше (позже создан)
        assert cloned_msg.timestamp > original_msg.timestamp
    
    def test_repr(self):
        """Проверяем строковое представление сообщения."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="test",
            targets=["target1", "target2"]
        )
        
        repr_str = repr(msg)
        assert "Message" in repr_str
        assert "type=command" in repr_str
        assert "sender=test" in repr_str
        assert "targets=" in repr_str
    
    def test_str(self):
        """Проверяем человекочитаемое представление сообщения."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="test",
            targets=["target"],
            content="Hello"
        )
        
        str_repr = str(msg)
        assert "type: general" in str_repr
        assert "sender: test" in str_repr
        assert "content: Hello" in str_repr


class TestConvenienceFunctions:
    """Тесты для удобных функций."""
    
    def test_create_message_function(self):
        """Проверяем функцию create_message."""
        msg = create_message(
            type=MessageType.DATA,
            sender="producer",
            targets=["consumer"],
            data_type="image",
            data=b"binary_data"
        )
        
        assert isinstance(msg, Message)
        assert msg.type == "data"
        assert msg.data_type == "image"
        assert msg.data == b"binary_data"


class TestRealWorldScenarios:
    """Тесты реальных сценариев использования."""
    
    def test_command_workflow(self):
        """Тестируем типичный workflow для команд."""
        # Создаем команду
        command = create_message(
            type=MessageType.COMMAND,
            sender="GUI",
            targets=["Worker1", "Worker2"],
            command="process_image",
            args={"image_id": 123, "format": "jpg"}
        ).set_priority(Priority.HIGH).set_need_ack(True)
        
        # Проверяем команду
        assert command.is_valid()
        assert command.priority == "high"
        assert command.need_ack == True
        
        # Сериализуем для отправки
        command_data = command.to_dict()
        assert command_data["command"] == "process_image"
        assert command_data["args"]["image_id"] == 123
        
    def test_log_workflow(self):
        """Тестируем типичный workflow для логов."""
        # Создаем лог
        log_msg = create_message(
            type=MessageType.LOG,
            sender="DatabaseModule",
            level=LogLevel.ERROR,
            message="Connection timeout",
            module="database"
        ).add_metadata("query_id", "q123").add_metadata("retry_count", 3)
        
        # Проверяем лог
        assert log_msg.is_valid()
        assert log_msg.targets == ["logger"]  # Должны быть дефолтные targets
        assert log_msg.metadata["query_id"] == "q123"
        
        # Конвертируем в текст для вывода в консоль
        log_text = log_msg.to_text()
        assert "ERROR" in log_text
        assert "Connection timeout" in log_text
        
    def test_request_response_workflow(self):
        """Тестируем workflow запрос-ответ."""
        # Создаем запрос
        request = create_message(
            type=MessageType.REQUEST,
            sender="Client",
            targets=["Server"],
            request_type="get_user_data",
            query={"user_id": 456},
            timeout=10.0
        )
        
        # Создаем ответ на запрос
        response = create_message(
            type=MessageType.RESPONSE,
            sender="Server",
            targets=["Client"],
            request_id=request.id,
            success=True,
            result={"user": {"id": 456, "name": "John"}}
        )
        
        # Проверяем связь запрос-ответ
        assert response.request_id == request.id
        assert response.success == True
        assert response.result["user"]["name"] == "John"
        
    def test_event_publishing(self):
        """Тестируем публикацию событий."""
        # Создаем событие
        event = create_message(
            type=MessageType.EVENT,
            sender="AuthService",
            event_type="user_logged_in",
            event_data={"user_id": 789, "timestamp": time.time()}
        )
        
        # Проверяем, что событие правильно настроено для широковещательной рассылки
        assert event.targets == ["all"]
        assert event.channel == "broadcast"
        assert event.event_type == "user_logged_in"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])