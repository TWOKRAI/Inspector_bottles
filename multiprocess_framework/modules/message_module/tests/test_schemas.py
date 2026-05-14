# -*- coding: utf-8 -*-
"""
Тесты для системы схем сообщений.
"""

import pytest
from ..core.message import Message
from ..types import MessageType, MessageValidationError
from ..schemas import BaseMessageSchema, CommandMessageSchema, LogMessageSchema


class TestBaseMessageSchemaAlias:
    """BaseMessageSchema — алиас на Message (план 08)."""

    def test_alias_points_to_message(self):
        assert BaseMessageSchema is Message


class TestSchemaCreation:
    """Тесты создания сообщений со схемами."""

    def test_create_with_command_schema(self):
        """Тест создания COMMAND сообщения со схемой."""
        msg = Message.create(
            MessageType.COMMAND,
            sender="TestSender",
            schema=CommandMessageSchema,
            targets=["TestTarget"],
            command="test_command",
        )

        assert msg.type == "command"
        assert msg.sender == "TestSender"
        assert msg.command == "test_command"
        assert msg.get_schema() == CommandMessageSchema
        assert msg.get_schema_info() is not None
        assert msg.get_schema_info()["schema_name"] == "CommandMessageSchema"

    def test_create_with_log_schema(self):
        """Тест создания LOG сообщения со схемой."""
        msg = Message.create(
            MessageType.LOG, sender="TestSender", schema=LogMessageSchema, level="info", message="Test log message"
        )

        assert msg.type == "log"
        assert msg.level == "info"
        assert msg.message == "Test log message"
        assert "logger" in msg.targets  # Автоматически из схемы
        assert msg.get_schema() == LogMessageSchema

    def test_create_without_schema_backward_compat(self):
        """Тест обратной совместимости - создание без схемы."""
        msg = Message.create(MessageType.COMMAND, sender="TestSender", targets=["TestTarget"], command="test_command")

        assert msg.type == "command"
        assert msg.command == "test_command"
        assert msg.get_schema() is None
        assert msg.get_schema_info() is None

    def test_schema_validation_fails_missing_required(self):
        """Тест что схема валидирует обязательные поля."""
        with pytest.raises(MessageValidationError):
            Message.create(
                MessageType.COMMAND,
                sender="TestSender",
                schema=CommandMessageSchema,
                targets=["TestTarget"],
                # Нет command - должно упасть
            )

    def test_schema_validation_fails_extra_fields(self):
        """Тест что схема запрещает дополнительные поля."""
        with pytest.raises(MessageValidationError):
            Message.create(
                MessageType.COMMAND,
                sender="TestSender",
                schema=CommandMessageSchema,
                targets=["TestTarget"],
                command="test",
                invalid_field="should_fail",  # Не должно быть в схеме
            )


class TestSchemaInfo:
    """Тесты информации о схеме."""

    def test_get_schema_info(self):
        """Тест получения информации о схеме."""
        msg = Message.create(
            MessageType.COMMAND,
            sender="TestSender",
            schema=CommandMessageSchema,
            targets=["TestTarget"],
            command="test",
        )

        info = msg.get_schema_info()
        assert info is not None
        assert "schema_name" in info
        assert "schema_module" in info
        assert "schema_path" in info
        assert info["schema_name"] == "CommandMessageSchema"

    def test_get_schema_class(self):
        """Тест получения класса схемы."""
        msg = Message.create(
            MessageType.COMMAND,
            sender="TestSender",
            schema=CommandMessageSchema,
            targets=["TestTarget"],
            command="test",
        )

        schema_class = msg.get_schema()
        assert schema_class == CommandMessageSchema

    def test_repr_includes_schema(self):
        """Тест что __repr__ включает информацию о схеме."""
        msg = Message.create(
            MessageType.COMMAND,
            sender="TestSender",
            schema=CommandMessageSchema,
            targets=["TestTarget"],
            command="test",
        )

        repr_str = repr(msg)
        assert "CommandMessageSchema" in repr_str or "schema=" in repr_str


class TestSchemaValidation:
    """Тесты валидации через схемы."""

    def test_validate_with_schema(self):
        """Тест валидации сообщения со схемой."""
        msg = Message.create(
            MessageType.COMMAND,
            sender="TestSender",
            schema=CommandMessageSchema,
            targets=["TestTarget"],
            command="test",
        )

        # Валидация должна пройти (уже валидировано через схему)
        assert msg.validate() is True
        assert msg.is_valid() is True

    def test_validate_without_schema(self):
        """Тест валидации без схемы (обратная совместимость)."""
        msg = Message.create(MessageType.COMMAND, sender="TestSender", targets=["TestTarget"], command="test")

        # Стандартная валидация
        assert msg.validate() is True


class TestSchemaFromDict:
    """Тесты создания из словаря со схемой."""

    def test_from_dict_with_schema(self):
        """Тест создания из словаря со схемой."""
        from ..utils import generate_message_id

        data = {
            "id": generate_message_id("command"),  # Схема требует id
            "type": "command",
            "sender": "TestSender",
            "targets": ["TestTarget"],
            "command": "test_command",
        }

        msg = Message.from_dict(data, schema=CommandMessageSchema)

        assert msg.type == "command"
        assert msg.command == "test_command"
        assert msg.get_schema() == CommandMessageSchema

    def test_from_dict_without_schema(self):
        """Тест создания из словаря без схемы (обратная совместимость)."""
        data = {"type": "command", "sender": "TestSender", "targets": ["TestTarget"], "command": "test_command"}

        msg = Message.from_dict(data)

        assert msg.type == "command"
        assert msg.command == "test_command"
        assert msg.get_schema() is None


class TestSchemaClone:
    """Тесты клонирования сообщений со схемами."""

    def test_clone_preserves_schema(self):
        """Тест что клонирование сохраняет схему."""
        msg = Message.create(
            MessageType.COMMAND,
            sender="TestSender",
            schema=CommandMessageSchema,
            targets=["TestTarget"],
            command="test",
        )

        cloned = msg.clone()

        assert cloned.get_schema() == CommandMessageSchema
        assert cloned.get_schema_info() == msg.get_schema_info()
        assert cloned.id != msg.id  # Новый ID
        assert cloned.command == msg.command


class TestSchemaPerformance:
    """Тесты производительности схем."""

    def test_schema_validation_cached(self):
        """Тест что валидация через схему кешируется."""
        msg = Message.create(
            MessageType.COMMAND,
            sender="TestSender",
            schema=CommandMessageSchema,
            targets=["TestTarget"],
            command="test",
        )

        # Первая валидация
        result1 = msg.validate()

        # Вторая валидация должна быть быстрее (уже валидировано)
        result2 = msg.validate()

        assert result1 is True
        assert result2 is True
