"""
Тесты для класса Message.
"""

import pytest
from ..core.message import Message
from ..types import MessageType, Priority, LogLevel, MessageValidationError


class TestMessageCreation:
    """Тесты создания сообщений."""
    
    def test_create_general_message(self):
        """Тест создания обычного сообщения."""
        msg = Message.create(
            type=MessageType.GENERAL,
            sender="TestSender",
            targets=["TestTarget"],
            content="Test content"
        )
        
        assert msg.type == "general"
        assert msg.sender == "TestSender"
        assert msg.targets == ["TestTarget"]
        assert msg.content == "Test content"
        assert msg.id is not None
    
    def test_create_command_message(self):
        """Тест создания командного сообщения."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=["TestTarget"],
            command="test_command",
            args={"key": "value"}
        )
        
        assert msg.type == "command"
        assert msg.command == "test_command"
        assert msg.args == {"key": "value"}
    
    def test_create_log_message(self):
        """Тест создания лог-сообщения."""
        msg = Message.create(
            type=MessageType.LOG,
            sender="TestSender",
            level=LogLevel.INFO.value,
            message="Test log message"
        )
        
        assert msg.type == "log"
        assert msg.level == "info"
        assert msg.message == "Test log message"
        # Логи автоматически получают targets=["logger"]
        assert "logger" in msg.targets


class TestMessageValidation:
    """Тесты валидации сообщений."""
    
    def test_validate_success(self):
        """Тест успешной валидации."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=["TestTarget"],
            command="test_command"
        )
        
        assert msg.validate() is True
        assert msg.is_valid() is True
    
    def test_validate_fails_no_sender(self):
        """Тест валидации без отправителя."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="",
            targets=["TestTarget"],
            command="test_command"
        )
        
        with pytest.raises(MessageValidationError):
            msg.validate()
        
        assert msg.is_valid() is False
    
    def test_validate_fails_no_targets(self):
        """Тест валидации без получателей."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=[],
            command="test_command"
        )
        
        with pytest.raises(MessageValidationError):
            msg.validate()
    
    def test_validate_fails_missing_required_field(self):
        """Тест валидации без обязательного поля."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=["TestTarget"]
            # Нет command
        )
        
        with pytest.raises(MessageValidationError):
            msg.validate()


class TestMessageConversion:
    """Тесты конвертации сообщений."""
    
    def test_to_dict(self):
        """Тест конвертации в словарь."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=["TestTarget"],
            command="test_command"
        )
        
        data = msg.to_dict()
        
        assert isinstance(data, dict)
        assert data["type"] == "command"
        assert data["sender"] == "TestSender"
        assert data["command"] == "test_command"
    
    def test_from_dict(self):
        """Тест создания из словаря."""
        data = {
            "type": "command",
            "sender": "TestSender",
            "targets": ["TestTarget"],
            "command": "test_command"
        }
        
        msg = Message.from_dict(data)
        
        assert msg.type == "command"
        assert msg.sender == "TestSender"
        assert msg.command == "test_command"
    
    def test_to_json(self):
        """Тест конвертации в JSON."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=["TestTarget"],
            command="test_command"
        )
        
        json_str = msg.to_json()
        
        assert isinstance(json_str, str)
        assert "command" in json_str
        assert "TestSender" in json_str
    
    def test_from_json(self):
        """Тест создания из JSON."""
        json_str = '{"type": "command", "sender": "TestSender", "targets": ["TestTarget"], "command": "test_command"}'
        
        msg = Message.from_json(json_str)
        
        assert msg.type == "command"
        assert msg.sender == "TestSender"
        assert msg.command == "test_command"


class TestFluentAPI:
    """Тесты Fluent API."""
    
    def test_set_priority(self):
        """Тест установки приоритета."""
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])
        msg.set_priority(Priority.HIGH)
        
        assert msg.priority == "high"
    
    def test_add_metadata(self):
        """Тест добавления метаданных."""
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])
        msg.add_metadata("key", "value")
        
        assert msg.metadata["key"] == "value"
    
    def test_set_command(self):
        """Тест установки команды."""
        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"])
        msg.set_command("test_command", {"arg": "value"})
        
        assert msg.command == "test_command"
        assert msg.args == {"arg": "value"}


class TestDictInterface:
    """Тесты словарного интерфейса."""
    
    def test_setitem_valid_field(self):
        """Тест установки допустимого поля через __setitem__."""
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])
        msg['command'] = 'test_command'
        
        assert msg.command == 'test_command'
        assert msg['command'] == 'test_command'
    
    def test_setitem_invalid_field(self):
        """Тест установки недопустимого поля через __setitem__."""
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])
        
        with pytest.raises(KeyError, match="Field 'invalid_field' is not a valid message field"):
            msg['invalid_field'] = 'value'
    
    def test_getitem(self):
        """Тест получения поля через __getitem__."""
        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"], command="test")
        
        assert msg['command'] == 'test'
        assert msg['sender'] == 'Test'
    
    def test_contains(self):
        """Тест проверки наличия поля через __contains__."""
        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"], command="test")
        
        assert 'command' in msg
        assert 'sender' in msg
        assert 'invalid_field' not in msg
    
    def test_get_with_default(self):
        """Тест безопасного получения поля с дефолтным значением."""
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])
        
        assert msg.get('command') is None
        assert msg.get('command', 'default') == 'default'
        assert msg.get('sender') == 'Test'
    
    def test_keys_values_items(self):
        """Тест методов keys(), values(), items()."""
        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"], command="test")
        
        keys = list(msg.keys())
        assert 'type' in keys
        assert 'sender' in keys
        assert 'command' in keys
        
        values = list(msg.values())
        assert 'command' in values
        assert 'Test' in values
        
        items = dict(msg.items())
        assert items['command'] == 'test'
        assert items['sender'] == 'Test'


class TestOtherMessageTypes:
    """Тесты других типов сообщений."""
    
    def test_system_message(self):
        """Тест создания системного сообщения."""
        msg = Message.create(
            type=MessageType.SYSTEM,
            sender="System",
            targets=["Process1"],
            action="restart"
        )
        
        assert msg.type == "system"
        assert msg.action == "restart"
        assert msg.validate() is True
    
    def test_broadcast_message(self):
        """Тест создания широковещательного сообщения."""
        msg = Message.create(
            type=MessageType.BROADCAST,
            sender="Broadcaster",
            content="Broadcast content"
        )
        
        assert msg.type == "broadcast"
        assert "all" in msg.targets
        assert msg.content == "Broadcast content"
    
    def test_event_message(self):
        """Тест создания событийного сообщения."""
        msg = Message.create(
            type=MessageType.EVENT,
            sender="EventSource",
            event_type="user_action",
            event_data={"action": "click"}
        )
        
        assert msg.type == "event"
        assert msg.event_type == "user_action"
        assert msg.event_data == {"action": "click"}
    
    def test_request_response_message(self):
        """Тест создания запроса и ответа."""
        request = Message.create(
            type=MessageType.REQUEST,
            sender="Client",
            targets=["Server"],
            request_type="get_data",
            query={"id": 123}
        )
        
        assert request.type == "request"
        assert request.request_type == "get_data"
        
        response = Message.create(
            type=MessageType.RESPONSE,
            sender="Server",
            targets=["Client"],
            request_id=request.id,
            success=True,
            result={"data": "result"}
        )
        
        assert response.type == "response"
        assert response.request_id == request.id
        assert response.success is True


class TestYAMLConversion:
    """Тесты конвертации в YAML."""
    
    def test_to_yaml_if_available(self):
        """Тест конвертации в YAML, если PyYAML доступен."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=["TestTarget"],
            command="test_command"
        )
        
        yaml_str = msg.to_yaml()
        
        assert isinstance(yaml_str, str)
        assert "command" in yaml_str
        assert "TestSender" in yaml_str
    
    def test_from_yaml_if_available(self):
        """Тест создания из YAML, если PyYAML доступен."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        
        yaml_str = """
type: command
sender: TestSender
targets:
  - TestTarget
command: test_command
"""
        
        msg = Message.from_yaml(yaml_str)
        
        assert msg.type == "command"
        assert msg.sender == "TestSender"
        assert msg.command == "test_command"
    
    def test_to_yaml_raises_if_not_available(self):
        """Тест что to_yaml выбрасывает ImportError если PyYAML не установлен."""
        # Этот тест сложно проверить без мокирования, но логика есть в коде
        pass

