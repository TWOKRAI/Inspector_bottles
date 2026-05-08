"""Тесты PluginContext — создание контекста из IProcessServices.

Проверяет:
- Создание из MockProcessServices
- process_name привязан к services.name
- Менеджеры передаются корректно
- Логирование делегируется services
- Backward-compat: старый API (process=, process_name=)
- with_config() создаёт новый контекст с тем же services
"""

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


# ---------------------------------------------------------------------------
# Создание PluginContext из MockProcessServices
# ---------------------------------------------------------------------------


def test_context_from_mock_services():
    """PluginContext(services=MockProcessServices(), config={}) создаётся без ошибок."""
    services = MockProcessServices(name="proc1")
    ctx = PluginContext(services=services, config={})
    assert ctx is not None


def test_context_process_name_from_services():
    """ctx.process_name == services.name."""
    services = MockProcessServices(name="my_process")
    ctx = PluginContext(services=services, config={})
    assert ctx.process_name == "my_process"


def test_context_config_stored():
    """ctx.config хранит переданный конфиг."""
    services = MockProcessServices()
    config = {"alpha": 1, "beta": "x"}
    ctx = PluginContext(services=services, config=config)
    assert ctx.config == config


def test_context_empty_config_by_default():
    """ctx.config == {} при отсутствии явного config."""
    services = MockProcessServices()
    ctx = PluginContext(services=services)
    assert ctx.config == {}


# ---------------------------------------------------------------------------
# Менеджеры
# ---------------------------------------------------------------------------


def test_context_managers_from_services():
    """ctx.worker_manager и ctx.command_manager привязаны к атрибутам services."""
    services = MockProcessServices()
    ctx = PluginContext(services=services, config={})
    assert ctx.worker_manager is services.worker_manager
    assert ctx.command_manager is services.command_manager


def test_context_router_manager_from_services():
    """ctx.router_manager берётся из services.router_manager."""
    from unittest.mock import MagicMock
    mock_router = MagicMock()
    services = MockProcessServices(router_manager=mock_router)
    ctx = PluginContext(services=services, config={})
    assert ctx.router_manager is mock_router


def test_context_memory_manager_from_services():
    """ctx.memory_manager берётся из services.memory_manager."""
    from unittest.mock import MagicMock
    mock_mem = MagicMock()
    services = MockProcessServices(memory_manager=mock_mem)
    ctx = PluginContext(services=services, config={})
    assert ctx.memory_manager is mock_mem


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------


def test_context_logging_log_info_from_services():
    """ctx.log_info вызывает services.log_info — запись попадает в services.logs."""
    services = MockProcessServices()
    ctx = PluginContext(services=services, config={})
    ctx.log_info("тест info через контекст")
    assert len(services.logs) == 1
    assert services.logs[0]["level"] == "INFO"
    assert services.logs[0]["msg"] == "тест info через контекст"


def test_context_logging_log_error_from_services():
    """ctx.log_error вызывает services.log_error — запись попадает в services.logs."""
    services = MockProcessServices()
    ctx = PluginContext(services=services, config={})
    ctx.log_error("тест error через контекст")
    assert services.logs[0]["level"] == "ERROR"
    assert services.logs[0]["msg"] == "тест error через контекст"


# ---------------------------------------------------------------------------
# Backward-compat: старый API (process=, process_name=)
# ---------------------------------------------------------------------------


def test_context_backward_compat_process_kwarg():
    """PluginContext(process=mock, process_name='test', config={}) — старый API работает."""
    services = MockProcessServices(name="legacy")
    # Передаём через устаревший аргумент process=
    ctx = PluginContext(process=services, process_name="test_override", config={})
    # process_name передан явно — должен использоваться он
    assert ctx.process_name == "test_override"
    # Менеджеры всё равно берутся из services (process)
    assert ctx.worker_manager is services.worker_manager


def test_context_backward_compat_process_without_name():
    """PluginContext(process=mock, config={}) без process_name — берёт services.name."""
    services = MockProcessServices(name="auto_name")
    ctx = PluginContext(process=services, config={})
    assert ctx.process_name == "auto_name"


# ---------------------------------------------------------------------------
# with_config()
# ---------------------------------------------------------------------------


def test_context_with_config_creates_new_context():
    """with_config() возвращает новый объект PluginContext."""
    services = MockProcessServices(name="proc")
    ctx = PluginContext(services=services, config={"old": True})
    new_ctx = ctx.with_config({"new_key": 42})
    assert new_ctx is not ctx


def test_context_with_config_has_new_config():
    """with_config() новый контекст содержит переданный конфиг."""
    services = MockProcessServices(name="proc")
    ctx = PluginContext(services=services, config={"old": True})
    new_ctx = ctx.with_config({"new_key": 42})
    assert new_ctx.config == {"new_key": 42}


def test_context_with_config_same_services():
    """with_config() новый контекст использует те же services (тот же worker_manager)."""
    services = MockProcessServices(name="proc")
    ctx = PluginContext(services=services, config={})
    new_ctx = ctx.with_config({"x": 1})
    # Менеджеры должны указывать на те же объекты
    assert new_ctx.worker_manager is services.worker_manager
    assert new_ctx.command_manager is services.command_manager


def test_context_with_config_process_name_preserved():
    """with_config() сохраняет process_name из services."""
    services = MockProcessServices(name="named_proc")
    ctx = PluginContext(services=services, config={})
    new_ctx = ctx.with_config({"val": 99})
    assert new_ctx.process_name == "named_proc"
