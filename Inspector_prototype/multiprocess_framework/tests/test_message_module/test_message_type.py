"""
Тесты для модуля message_types.py

Проверяем корректность работы типов сообщений, enum и схем.
"""
import pytest
from dataclasses import asdict
from multiprocess_framework.modules.Message_module.message_types import *


class TestMessageTypes:
    """Тесты для типов сообщений и enum."""
    
    def test_message_type_enum(self):
        """Проверяем, что все типы сообщений доступны."""
        assert MessageType.GENERAL.value == "general"
        assert MessageType.COMMAND.value == "command"
        assert MessageType.LOG.value == "log"
        assert MessageType.SYSTEM.value == "system"
        assert MessageType.BROADCAST.value == "broadcast"
        assert MessageType.DATA.value == "data"
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.EVENT.value == "event"
        
    def test_priority_enum(self):
        """Проверяем приоритеты."""
        assert Priority.LOW.value == "low"
        assert Priority.NORMAL.value == "normal"
        assert Priority.HIGH.value == "high"
        assert Priority.URGENT.value == "urgent"
        
    def test_log_level_enum(self):
        """Проверяем уровни логирования."""
        assert LogLevel.DEBUG.value == "debug"
        assert LogLevel.INFO.value == "info"
        assert LogLevel.WARNING.value == "warning"
        assert LogLevel.ERROR.value == "error"
        assert LogLevel.CRITICAL.value == "critical"


class TestMessageSchema:
    """Тесты для схемы сообщения."""
    
    def test_basic_schema_creation(self):
        """Проверяем создание базовой схемы сообщения."""
        schema = MessageSchema(
            id="test_123",
            type="general",
            sender="test_sender",
            targets=["target1", "target2"],
            timestamp=1234567890.0
        )
        
        assert schema.id == "test_123"
        assert schema.type == "general"
        assert schema.sender == "test_sender"
        assert schema.targets == ["target1", "target2"]
        assert schema.timestamp == 1234567890.0
        assert schema.priority == "normal"  # значение по умолчанию
        assert schema.routers == ["internal"]  # значение по умолчанию
        
    def test_schema_with_optional_fields(self):
        """Проверяем создание схемы с опциональными полями."""
        schema = MessageSchema(
            id="test_123",
            type="command",
            sender="sender",
            targets=["target"],
            timestamp=1234567890.0,
            priority="high",
            channel="queue",
            metadata={"key": "value"},
            command="test_command",
            args={"param": "value"},
            need_ack=True
        )
        
        assert schema.priority == "high"
        assert schema.channel == "queue"
        assert schema.metadata == {"key": "value"}
        assert schema.command == "test_command"
        assert schema.args == {"param": "value"}
        assert schema.need_ack == True
        
    def test_schema_default_values(self):
        """Проверяем значения по умолчанию."""
        schema = MessageSchema(
            id="test",
            type="general",
            sender="sender",
            targets=["target"],
            timestamp=1234567890.0
        )
        
        # Проверяем, что опциональные поля имеют правильные значения по умолчанию
        assert schema.priority == "normal"
        assert schema.routers == ["internal"]
        assert schema.channel is None
        assert schema.metadata == {}
        assert schema.content is None
        assert schema.command is None
        assert schema.args == {}
        assert schema.need_ack == False
        assert schema.level is None
        assert schema.message is None
        assert schema.module == "main"
        assert schema.action is None
        assert schema.data is None
        assert schema.exclude == []
        assert schema.data_type is None
        assert schema.use_shared_memory == False
        assert schema.memory_key is None
        assert schema.request_type is None
        assert schema.query is None
        assert schema.timeout == 5.0
        assert schema.request_id is None
        assert schema.success == True
        assert schema.result is None
        assert schema.error is None
        assert schema.event_type is None
        assert schema.event_data is None


class TestMessageTypeDefaults:
    """Тесты для конфигурации типов сообщений."""
    
    def test_defaults_exist_for_all_types(self):
        """Проверяем, что для всех типов сообщений есть конфигурация."""
        for message_type in MessageType:
            assert message_type in MESSAGE_TYPE_DEFAULTS
            
    def test_general_defaults(self):
        """Проверяем дефолты для GENERAL сообщений."""
        defaults = MESSAGE_TYPE_DEFAULTS[MessageType.GENERAL]
        assert defaults["channel"] == "queue"
        assert "content" in defaults["required_fields"]
        
    def test_log_defaults(self):
        """Проверяем дефолты для LOG сообщений."""
        defaults = MESSAGE_TYPE_DEFAULTS[MessageType.LOG]
        assert defaults["channel"] == "log"
        assert defaults["targets"] == ["logger"]
        assert defaults["routers"] == ["log"]
        assert "level" in defaults["required_fields"]
        assert "message" in defaults["required_fields"]
        
    def test_broadcast_defaults(self):
        """Проверяем дефолты для BROADCAST сообщений."""
        defaults = MESSAGE_TYPE_DEFAULTS[MessageType.BROADCAST]
        assert defaults["channel"] == "broadcast"
        assert defaults["targets"] == ["all"]
        assert "content" in defaults["required_fields"]
        
    def test_event_defaults(self):
        """Проверяем дефолты для EVENT сообщений."""
        defaults = MESSAGE_TYPE_DEFAULTS[MessageType.EVENT]
        assert defaults["channel"] == "broadcast"
        assert defaults["targets"] == ["all"]
        assert "event_type" in defaults["required_fields"]


class TestMessageTypeExcludeFields:
    """Тесты для исключения полей при сериализации."""
    
    def test_log_exclude_fields(self):
        """Проверяем, что для логов исключаются routers."""
        exclude_fields = MESSAGE_TYPE_EXCLUDE_FIELDS.get(MessageType.LOG, set())
        assert "routers" in exclude_fields


if __name__ == "__main__":
    pytest.main([__file__, "-v"])