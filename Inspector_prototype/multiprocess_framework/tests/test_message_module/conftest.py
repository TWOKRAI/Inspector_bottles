"""
Общие фикстуры для тестов Message_module.
"""
import pytest
from multiprocess_framework.modules.Message_module import Message, MessageType, Priority, LogLevel


@pytest.fixture
def sample_general_message():
    """
    Создает пример GENERAL сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа GENERAL
    """
    return Message.create(
        type=MessageType.GENERAL,
        sender="test_sender",
        targets=["target1", "target2"],
        content={"message": "Hello World"}
    )


@pytest.fixture
def sample_command_message():
    """
    Создает пример COMMAND сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа COMMAND
    """
    return Message.create(
        type=MessageType.COMMAND,
        sender="GUI",
        targets=["Worker"],
        command="process_image",
        args={"image_id": 123, "format": "jpg"}
    )


@pytest.fixture
def sample_log_message():
    """
    Создает пример LOG сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа LOG
    """
    return Message.create(
        type=MessageType.LOG,
        sender="VisionProcess",
        level=LogLevel.ERROR,
        message="Failed to capture frame",
        module="camera"
    )


@pytest.fixture
def sample_request_message():
    """
    Создает пример REQUEST сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа REQUEST
    """
    return Message.create(
        type=MessageType.REQUEST,
        sender="Client",
        targets=["Server"],
        request_type="get_user_data",
        query={"user_id": 456},
        timeout=10.0
    )


@pytest.fixture
def sample_response_message(sample_request_message):
    """
    Создает пример RESPONSE сообщения для тестов.
    
    Args:
        sample_request_message: Фикстура запроса для создания ответа
        
    Returns:
        Message: Пример сообщения типа RESPONSE
    """
    return Message.create(
        type=MessageType.RESPONSE,
        sender="Server",
        targets=["Client"],
        request_id=sample_request_message.id,
        success=True,
        result={"user": {"id": 456, "name": "John"}}
    )


@pytest.fixture
def sample_event_message():
    """
    Создает пример EVENT сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа EVENT
    """
    return Message.create(
        type=MessageType.EVENT,
        sender="Camera"
    ).set_event("frame_captured", {"frame_id": 999, "fps": 30})


@pytest.fixture
def sample_broadcast_message():
    """
    Создает пример BROADCAST сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа BROADCAST
    """
    return Message.create(
        type=MessageType.BROADCAST,
        sender="ProcessManager",
        content="System update available",
        exclude=["Logger"]
    )


@pytest.fixture
def sample_system_message():
    """
    Создает пример SYSTEM сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа SYSTEM
    """
    return Message.create(
        type=MessageType.SYSTEM,
        sender="ProcessManager",
        targets=["all"]
    ).set_system_action("shutdown", {"reason": "user_request"})


@pytest.fixture
def sample_data_message():
    """
    Создает пример DATA сообщения для тестов.
    
    Returns:
        Message: Пример сообщения типа DATA
    """
    return Message.create(
        type=MessageType.DATA,
        sender="Camera",
        targets=["VisionProcess"],
        data_type="image",
        use_shared_memory=True,
        memory_key="frame_buffer_001"
    )


@pytest.fixture
def message_dict():
    """
    Создает словарь с данными сообщения для тестов парсинга.
    
    Returns:
        dict: Словарь с данными сообщения
    """
    return {
        "type": "general",
        "sender": "test_sender",
        "targets": ["target1"],
        "content": {"key": "value"},
        "priority": "high",
        "metadata": {"user_id": 12345}
    }


@pytest.fixture
def message_json_string(message_dict):
    """
    Создает JSON строку с данными сообщения для тестов парсинга.
    
    Args:
        message_dict: Фикстура словаря сообщения
        
    Returns:
        str: JSON строка с данными сообщения
    """
    import json
    return json.dumps(message_dict)


@pytest.fixture
def yaml_available():
    """
    Проверяет доступность PyYAML для тестов.
    
    Returns:
        bool: True если PyYAML доступен, иначе False
        
    Yields:
        bool: Доступность PyYAML
    """
    try:
        import yaml
        yield True
    except ImportError:
        yield False

