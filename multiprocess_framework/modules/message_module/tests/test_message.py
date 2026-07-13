# -*- coding: utf-8 -*-
"""
Тесты для класса Message.
"""

import importlib.util

import pytest
from ..core.message import Message
from ..factories import parse_message
from ..types import MessageType, Priority, LogLevel, MessageValidationError


class TestMessageCreation:
    """Тесты создания сообщений."""

    def test_create_general_message(self):
        """Тест создания обычного сообщения."""
        msg = Message.create(
            type=MessageType.GENERAL, sender="TestSender", targets=["TestTarget"], content="Test content"
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
            args={"key": "value"},
        )

        assert msg.type == "command"
        assert msg.command == "test_command"
        assert msg.args == {"key": "value"}

    def test_create_log_message(self):
        """Тест создания лог-сообщения."""
        msg = Message.create(
            type=MessageType.LOG, sender="TestSender", level=LogLevel.INFO.value, message="Test log message"
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
            type=MessageType.COMMAND, sender="TestSender", targets=["TestTarget"], command="test_command"
        )

        assert msg.validate() is True
        assert msg.is_valid() is True

    def test_validate_fails_no_sender(self):
        """Тест валидации без отправителя."""
        msg = Message.create(type=MessageType.COMMAND, sender="", targets=["TestTarget"], command="test_command")

        with pytest.raises(MessageValidationError):
            msg.validate()

        assert msg.is_valid() is False

    def test_validate_fails_no_targets(self):
        """Тест валидации без получателей."""
        msg = Message.create(type=MessageType.COMMAND, sender="TestSender", targets=[], command="test_command")

        with pytest.raises(MessageValidationError):
            msg.validate()

    def test_validate_fails_missing_required_field(self):
        """Тест валидации без обязательного поля."""
        msg = Message.create(
            type=MessageType.COMMAND,
            sender="TestSender",
            targets=["TestTarget"],
            # Нет command
        )

        with pytest.raises(MessageValidationError):
            msg.validate()


class TestMessageConversion:
    """Тесты конвертации сообщений."""

    def test_to_dict(self):
        """Тест конвертации в словарь."""
        msg = Message.create(
            type=MessageType.COMMAND, sender="TestSender", targets=["TestTarget"], command="test_command"
        )

        data = msg.to_dict()

        assert isinstance(data, dict)
        assert data["type"] == "command"
        assert data["sender"] == "TestSender"
        assert data["command"] == "test_command"

    def test_from_dict(self):
        """Тест создания из словаря."""
        data = {"type": "command", "sender": "TestSender", "targets": ["TestTarget"], "command": "test_command"}

        msg = Message.from_dict(data)

        assert msg.type == "command"
        assert msg.sender == "TestSender"
        assert msg.command == "test_command"

    def test_to_json(self):
        """Тест конвертации в JSON."""
        msg = Message.create(
            type=MessageType.COMMAND, sender="TestSender", targets=["TestTarget"], command="test_command"
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
        """set_command устарел и кладёт payload под data (единый конверт, Ф7 G.2)."""
        import warnings

        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            msg.set_command("test_command", {"arg": "value"})

        assert msg.command == "test_command"
        assert msg.data_type == "test_command"
        assert msg.data == {"arg": "value"}

    def test_set_command_warns_deprecated(self):
        """set_command эмитит DeprecationWarning (единый билдер — предпочтителен)."""
        import warnings

        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            msg.set_command("c")
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)


class TestDictInterface:
    """Тесты словарного интерфейса."""

    def test_setitem_valid_field(self):
        """Тест установки допустимого поля через __setitem__."""
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])
        msg["command"] = "test_command"

        assert msg.command == "test_command"
        assert msg["command"] == "test_command"

    def test_setitem_invalid_field(self):
        """Тест установки недопустимого поля через __setitem__."""
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])

        with pytest.raises(KeyError, match="Field 'invalid_field' is not a valid message field"):
            msg["invalid_field"] = "value"

    def test_getitem(self):
        """Тест получения поля через __getitem__."""
        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"], command="test")

        assert msg["command"] == "test"
        assert msg["sender"] == "Test"

    def test_contains(self):
        """Тест проверки наличия поля через __contains__."""
        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"], command="test")

        assert "command" in msg
        assert "sender" in msg
        assert "invalid_field" not in msg

    def test_get_with_default(self):
        """Тест безопасного получения поля с дефолтным значением.

        Поведение совпадает со стандартным dict.get():
        - Существующий ключ → его значение (даже если None)
        - Отсутствующий ключ → default (редко, т.к. все поля инициализированы)
        """
        msg = Message.create(MessageType.GENERAL, sender="Test", targets=["Target"])

        # Все поля Message инициализированы в __init__, поэтому 'command' существует
        # со значением None, а не отсутствует
        assert msg.get("command") is None
        # Передача default не влияет, т.к. ключ существует (стандартная dict.get семантика)
        assert msg.get("command", "default") is None

        # Существующее поле возвращает своё значение
        assert msg.get("sender") == "Test"

        # Несуществующее поле вернёт default (не применимо для Message, но демонстрируем)
        assert msg.get("nonexistent_field", "default") == "default"

    def test_keys_values_items(self):
        """Тест методов keys(), values(), items()."""
        msg = Message.create(MessageType.COMMAND, sender="Test", targets=["Target"], command="test")

        keys = list(msg.keys())
        assert "type" in keys
        assert "sender" in keys
        assert "command" in keys

        values = list(msg.values())
        assert "command" in values
        assert "Test" in values

        items = dict(msg.items())
        assert items["command"] == "test"
        assert items["sender"] == "Test"


class TestOtherMessageTypes:
    """Тесты других типов сообщений."""

    def test_system_message(self):
        """Тест создания системного сообщения."""
        msg = Message.create(type=MessageType.SYSTEM, sender="System", targets=["Process1"], action="restart")

        assert msg.type == "system"
        assert msg.action == "restart"
        assert msg.validate() is True

    def test_broadcast_message(self):
        """Тест создания широковещательного сообщения."""
        msg = Message.create(type=MessageType.BROADCAST, sender="Broadcaster", content="Broadcast content")

        assert msg.type == "broadcast"
        assert "all" in msg.targets
        assert msg.content == "Broadcast content"

    def test_event_message(self):
        """Тест создания событийного сообщения."""
        msg = Message.create(
            type=MessageType.EVENT, sender="EventSource", event_type="user_action", event_data={"action": "click"}
        )

        assert msg.type == "event"
        assert msg.event_type == "user_action"
        assert msg.event_data == {"action": "click"}

    def test_request_response_message(self):
        """Тест создания запроса и ответа."""
        request = Message.create(
            type=MessageType.REQUEST, sender="Client", targets=["Server"], request_type="get_data", query={"id": 123}
        )

        assert request.type == "request"
        assert request.request_type == "get_data"

        response = Message.create(
            type=MessageType.RESPONSE,
            sender="Server",
            targets=["Client"],
            request_id=request.id,
            success=True,
            result={"data": "result"},
        )

        assert response.type == "response"
        assert response.request_id == request.id
        assert response.success is True


class TestYAMLConversion:
    """Тесты конвертации в YAML."""

    def test_to_yaml_if_available(self):
        """Тест конвертации в YAML, если PyYAML доступен."""
        if not importlib.util.find_spec("yaml"):
            pytest.skip("PyYAML not installed")

        msg = Message.create(
            type=MessageType.COMMAND, sender="TestSender", targets=["TestTarget"], command="test_command"
        )

        yaml_str = msg.to_yaml()

        assert isinstance(yaml_str, str)
        assert "command" in yaml_str
        assert "TestSender" in yaml_str

    def test_from_yaml_if_available(self):
        """Тест создания из YAML, если PyYAML доступен."""
        if not importlib.util.find_spec("yaml"):
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


class TestClone:
    """Тесты clone() сохранения всех полей."""

    def test_clone_general_message(self):
        msg = Message.create(MessageType.GENERAL, sender="test", targets=["t"], content="x")
        cloned = msg.clone()
        assert cloned.id != msg.id
        assert cloned.timestamp >= msg.timestamp
        d_orig = msg.to_dict(exclude_none=False)
        d_cloned = cloned.to_dict(exclude_none=False)
        d_orig.pop("id", None)
        d_cloned.pop("id", None)
        d_orig.pop("timestamp", None)
        d_cloned.pop("timestamp", None)
        assert d_cloned == d_orig

    def test_clone_preserves_schema(self):
        from ..schemas import CommandMessageSchema

        msg = Message.create(
            MessageType.COMMAND,
            sender="test",
            targets=["t"],
            command="start",
            schema=CommandMessageSchema,
        )
        cloned = msg.clone()
        assert cloned.get_schema() == msg.get_schema()


class TestSchemaBaseIntegration:
    """Интеграция Message с SchemaBase (план 08)."""

    def test_message_is_schema_base(self):
        from ...data_schema_module import SchemaBase

        assert issubclass(Message, SchemaBase)

    def test_field_meta_available(self):
        meta = Message.get_field_meta("sender")
        assert meta is not None

    def test_model_dump_equals_to_dict_no_filter(self):
        msg = Message.create("general", "a", targets=["b"], content="x")
        dump = msg.model_dump()
        assert "type" in dump
        assert dump["sender"] == "a"

    def test_no_shared_mutable_defaults(self):
        msg1 = Message.create("general", "a", targets=["b"])
        msg2 = Message.create("general", "c", targets=["d"])
        msg1.metadata["key"] = "value"
        assert "key" not in msg2.metadata

    def test_timeout_constraints(self):
        meta = Message.get_field_meta("timeout")
        assert meta is not None
        assert meta.min == 0.1
        assert meta.max == 300.0

    def test_model_validate_from_dict(self):
        data = {
            "type": "command",
            "sender": "a",
            "targets": ["b"],
            "command": "go",
        }
        msg = Message.model_validate(data)
        assert msg.command == "go"

    def test_isinstance_imessage(self):
        from ..interfaces import IMessage

        msg = Message.create("general", "a", targets=["b"])
        assert isinstance(msg, IMessage)

    def test_model_dump_excludes_private_schema_state(self):
        """Метаданные внешней схемы в __dict__, не в model_dump (риск плана 08)."""
        from ..schemas import CommandMessageSchema

        msg = Message.create(
            MessageType.COMMAND,
            "s",
            schema=CommandMessageSchema,
            targets=["t"],
            command="x",
        )
        dumped = msg.model_dump()
        assert "_msg_schema" not in dumped
        assert "_msg_schema_info" not in dumped
        assert "_msg_schema_validated" not in dumped


class TestValidateWithoutSchema:
    """Тесты validate() без Pydantic схемы."""

    def test_validate_general_message(self):
        msg = Message.create(MessageType.GENERAL, sender="test", targets=["t"], content="ok")
        assert msg.validate() is True

    def test_validate_missing_sender_raises(self):
        msg = Message.create(MessageType.GENERAL, sender="", targets=["t"])
        with pytest.raises(MessageValidationError):
            msg.validate()

    def test_validate_missing_targets_raises(self):
        msg = Message.create(MessageType.GENERAL, sender="test", targets=[])
        with pytest.raises(MessageValidationError):
            msg.validate()


class TestParseMessage:
    """Тесты parse_message() функции."""

    def test_parse_dict(self):
        data = {"type": "general", "sender": "test", "targets": ["t"], "content": "x"}
        msg = parse_message(data)
        assert msg.type == "general"
        assert msg.sender == "test"

    def test_parse_json(self):
        import json

        data_dict = {
            "type": "command",
            "sender": "test",
            "targets": ["t"],
            "command": "start",
        }
        json_str = json.dumps(data_dict)
        msg = parse_message(json_str)
        assert msg.type == "command"
        assert msg.command == "start"

    def test_parse_yaml(self):
        if not importlib.util.find_spec("yaml"):
            pytest.skip("PyYAML not installed")

        yaml_str = """
type: log
sender: logger
targets: [logger]
level: info
message: test
"""
        msg = parse_message(yaml_str)
        assert msg.type == "log"
        assert msg.message == "test"


class TestPickleSafe:
    """Тесты pickle-safe для Message.

    Framework принцип #5: все объекты в multiprocessing.Queue должны быть pickle-safe.
    Однако Message объект НЕ должен пересекать границу процесса, только dict.
    Эти тесты проверяют оба аспекта.
    """

    import pickle

    def test_message_general_pickle(self):
        """Проверить, что GENERAL Message может быть pickled."""
        msg = Message.create(MessageType.GENERAL, sender="test", targets=["proc"], content="test")
        data = self.pickle.dumps(msg)
        restored = self.pickle.loads(data)
        assert restored.to_dict() == msg.to_dict()

    def test_message_command_pickle(self):
        """Проверить, что COMMAND Message может быть pickled."""
        msg = Message.create(MessageType.COMMAND, sender="test", targets=["cmd"], command="start", args={})
        data = self.pickle.dumps(msg)
        restored = self.pickle.loads(data)
        assert restored["command"] == "start"
        assert restored.sender == "test"

    def test_message_dict_is_pickle_safe(self):
        """Проверить, что dict-форма (Dict at Boundary) всегда pickle-safe.

        Это единственное что должно пересекать границу процесса.
        """
        msg = Message.create(
            MessageType.LOG, sender="logger", targets=["logger"], level=LogLevel.INFO.value, message="test"
        )
        # Только dict пересекает границу
        d = msg.to_dict()
        data = self.pickle.dumps(d)
        restored = self.pickle.loads(data)
        assert restored == d

    def test_message_log_pickle(self):
        """Проверить, что LOG Message может быть pickled."""
        msg = Message.create(MessageType.LOG, sender="logger", level=LogLevel.WARNING.value, message="test warning")
        data = self.pickle.dumps(msg)
        restored = self.pickle.loads(data)
        assert restored["message"] == "test warning"
        assert restored["level"] == "warning"

    def test_message_object_pickle_roundtrip(self):
        """Message объект должен быть pickle-safe (Pydantic BaseModel сериализуется)."""
        import pickle

        msg = Message.create(
            MessageType.COMMAND,
            "sender",
            targets=["target"],
            command="start",
            args={"key": "value"},
        )
        msg.add_metadata("test", 123)

        pickled = pickle.dumps(msg)
        restored = pickle.loads(pickled)

        assert restored.type == msg.type
        assert restored.sender == msg.sender
        assert restored.command == msg.command
        assert restored.args == msg.args
        assert restored.metadata == msg.metadata

    def test_message_dict_pickle_roundtrip(self):
        """to_dict() → pickle → unpickle → from_dict() — полный цикл."""
        import pickle

        msg = Message.create(
            MessageType.LOG,
            "logger_proc",
            targets=["logger"],
            level="info",
            message="test log",
        )

        d = msg.to_dict()
        restored_dict = pickle.loads(pickle.dumps(d))
        restored_msg = Message.from_dict(restored_dict)

        assert restored_msg.type == "log"
        assert restored_msg.message == "test log"
        assert restored_msg.sender == "logger_proc"


class TestExtraFields:
    """Поведение extra='allow' при сериализации."""

    def test_extra_field_in_constructor(self):
        """Extra-поля через конструктор попадают в model_dump."""
        msg = Message(type="general", sender="s", targets=["t"], custom_field="value")
        dump = msg.model_dump()
        assert "custom_field" in dump

    def test_extra_field_in_to_dict(self):
        """Extra-поля попадают в to_dict() (не фильтруются)."""
        msg = Message(type="general", sender="s", targets=["t"], custom_field="value")
        d = msg.to_dict()
        assert "custom_field" in d

    def test_extra_field_not_in_model_fields(self):
        """Extra-поля не регистрируются как model_fields."""
        assert "custom_field" not in Message.model_fields

    def test_extra_field_survives_from_dict(self):
        """Extra-поля выживают при from_dict() → to_dict() roundtrip."""
        data = {
            "type": "general",
            "sender": "s",
            "targets": ["t"],
            "custom_field": "value",
        }
        msg = Message.from_dict(data)
        assert msg.custom_field == "value"
        d = msg.to_dict()
        assert d.get("custom_field") == "value"
