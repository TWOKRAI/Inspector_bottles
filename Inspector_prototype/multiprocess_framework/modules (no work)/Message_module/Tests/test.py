import pytest
from Message_module.message_manager import MessageManager, CommandMessage, LogMessage, SystemMessage, MessageValidationError

def test_create_command_message():
    manager = MessageManager("test_process")
    command_msg = manager.create_command_message(
        command="test_command",
        args={"param": "value"},
        targets=["target1", "target2"]
    )
    assert isinstance(command_msg, CommandMessage)
    assert command_msg.command == "test_command"
    assert command_msg.args == {"param": "value"}
    assert command_msg.targets == ["target1", "target2"]

def test_create_log_message():
    manager = MessageManager("test_process")
    log_msg = manager.create_log_message(
        level="info",
        message="Test message"
    )
    assert isinstance(log_msg, LogMessage)
    assert log_msg.level == "info"
    assert log_msg.message == "Test message"
    assert log_msg.targets == ["logger"]

def test_create_system_message():
    manager = MessageManager("test_process")
    system_msg = manager.create_system_message(
        msg_type="system",
        data={"key": "value"},
        targets=["target1", "target2"]
    )
    assert isinstance(system_msg, SystemMessage)
    assert system_msg.type == "system"
    assert system_msg.data == {"key": "value"}
    assert system_msg.targets == ["target1", "target2"]

def test_command_message_validation():
    manager = MessageManager("test_process")
    with pytest.raises(MessageValidationError):
        manager.create_command_message(
            command="",
            args={"param": "value"},
            targets=["target1", "target2"]
        )

def test_log_message_validation():
    manager = MessageManager("test_process")
    with pytest.raises(MessageValidationError):
        manager.create_log_message(
            level="",
            message="Test message"
        )

def test_system_message_validation():
    manager = MessageManager("test_process")
    with pytest.raises(MessageValidationError):
        manager.create_system_message(
            msg_type="system",
            data=None,
            targets=["target1", "target2"]
        )

def test_message_conversion():
    manager = MessageManager("test_process")
    command_msg = manager.create_command_message(
        command="test_command",
        args={"param": "value"},
        targets=["target1", "target2"]
    )
    # Test to_dict
    assert isinstance(command_msg.to_dict(), dict)
    # Test to_json
    assert isinstance(command_msg.to_json(), str)
    # Test to_yaml
    assert isinstance(command_msg.to_yaml(), str)
    # Test to_text
    assert isinstance(command_msg.to_text(), str)

def test_message_exclude_fields():
    manager = MessageManager("test_process")
    command_msg = manager.create_command_message(
        command="test_command",
        args={"param": "value"},
        targets=["target1", "target2"]
    )
    data = command_msg.to_dict(exclude_fields={"args"})
    assert "args" not in data

def test_message_include_fields():
    manager = MessageManager("test_process")
    command_msg = manager.create_command_message(
        command="test_command",
        args={"param": "value"},
        targets=["target1", "target2"]
    )
    data = command_msg.to_dict(include_fields={"id", "type"})
    assert list(data.keys()) == ["id", "type"]
