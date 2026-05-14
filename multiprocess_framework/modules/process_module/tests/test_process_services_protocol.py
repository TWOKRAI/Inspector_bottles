"""Тесты Protocol-контрактов IProcessServices и mock-реализаций.

Проверяет:
- MockProcessServices удовлетворяет IProcessServices (structural subtyping)
- MockWorkerManager удовлетворяет IPluginWorkerManager
- MockCommandManager удовлетворяет IPluginCommandManager
- Запись вызовов в mock-объектах
"""

from multiprocess_framework.modules.process_module.plugins.interfaces import (
    IPluginCommandManager,
    IPluginWorkerManager,
    IProcessServices,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockCommandManager,
    MockProcessServices,
    MockWorkerManager,
)


# ---------------------------------------------------------------------------
# Protocol — isinstance-проверки
# ---------------------------------------------------------------------------


def test_mock_satisfies_protocol():
    """MockProcessServices проходит isinstance-проверку IProcessServices."""
    services = MockProcessServices()
    assert isinstance(services, IProcessServices)


def test_mock_worker_manager_satisfies_protocol():
    """MockWorkerManager проходит isinstance-проверку IPluginWorkerManager."""
    wm = MockWorkerManager()
    assert isinstance(wm, IPluginWorkerManager)


def test_mock_command_manager_satisfies_protocol():
    """MockCommandManager проходит isinstance-проверку IPluginCommandManager."""
    cm = MockCommandManager()
    assert isinstance(cm, IPluginCommandManager)


# ---------------------------------------------------------------------------
# Логирование — запись в services.logs
# ---------------------------------------------------------------------------


def test_mock_logs_recorded_info():
    """log_info записывает запись с level=INFO в services.logs."""
    services = MockProcessServices()
    services.log_info("тестовое info-сообщение")
    assert len(services.logs) == 1
    assert services.logs[0]["level"] == "INFO"
    assert services.logs[0]["msg"] == "тестовое info-сообщение"


def test_mock_logs_recorded_warning():
    """log_warning записывает запись с level=WARNING в services.logs."""
    services = MockProcessServices()
    services.log_warning("предупреждение")
    assert services.logs[0]["level"] == "WARNING"
    assert services.logs[0]["msg"] == "предупреждение"


def test_mock_logs_recorded_error():
    """log_error записывает запись с level=ERROR в services.logs."""
    services = MockProcessServices()
    services.log_error("ошибка!")
    assert services.logs[0]["level"] == "ERROR"
    assert services.logs[0]["msg"] == "ошибка!"


def test_mock_logs_recorded_multiple():
    """Несколько вызовов накапливаются в services.logs по порядку."""
    services = MockProcessServices()
    services.log_info("первое")
    services.log_warning("второе")
    services.log_error("третье")
    assert len(services.logs) == 3
    assert [e["level"] for e in services.logs] == ["INFO", "WARNING", "ERROR"]


# ---------------------------------------------------------------------------
# IPC — send_message / receive_message
# ---------------------------------------------------------------------------


def test_mock_send_message_recorded():
    """send_message записывает сообщение в services.sent_messages и возвращает True."""
    services = MockProcessServices()
    result = services.send_message("target_process", {"type": "ping"})
    assert result is True
    assert len(services.sent_messages) == 1
    assert services.sent_messages[0]["target"] == "target_process"
    assert services.sent_messages[0]["message"] == {"type": "ping"}


def test_mock_send_message_multiple():
    """Несколько send_message накапливаются в sent_messages по порядку."""
    services = MockProcessServices()
    services.send_message("proc_a", {"type": "a"})
    services.send_message("proc_b", {"type": "b"})
    assert len(services.sent_messages) == 2
    assert services.sent_messages[1]["target"] == "proc_b"


def test_mock_receive_message_returns_none():
    """receive_message всегда возвращает None (нет входящих сообщений)."""
    services = MockProcessServices()
    result = services.receive_message()
    assert result is None


def test_mock_receive_message_with_timeout_returns_none():
    """receive_message с timeout тоже возвращает None."""
    services = MockProcessServices()
    result = services.receive_message(timeout=0.1)
    assert result is None


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------


def test_mock_get_config_existing_key():
    """get_config возвращает значение из config по ключу."""
    services = MockProcessServices(config={"threshold": 42, "mode": "fast"})
    assert services.get_config("threshold") == 42
    assert services.get_config("mode") == "fast"


def test_mock_get_config_missing_key_default_none():
    """get_config возвращает None для отсутствующего ключа."""
    services = MockProcessServices(config={})
    assert services.get_config("missing") is None


def test_mock_get_config_missing_key_custom_default():
    """get_config возвращает переданный default для отсутствующего ключа."""
    services = MockProcessServices()
    assert services.get_config("key", default="fallback") == "fallback"


# ---------------------------------------------------------------------------
# Имя процесса
# ---------------------------------------------------------------------------


def test_mock_default_name():
    """MockProcessServices по умолчанию имеет name='mock'."""
    services = MockProcessServices()
    assert services.name == "mock"


def test_mock_custom_name():
    """MockProcessServices принимает кастомное имя."""
    services = MockProcessServices(name="my_process")
    assert services.name == "my_process"
