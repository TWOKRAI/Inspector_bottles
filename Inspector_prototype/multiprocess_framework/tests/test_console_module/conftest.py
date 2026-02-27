"""
Фикстуры для тестов Console_module.
"""

import pytest
from multiprocessing import Queue
from multiprocess_framework.modules.Console_module import ConsoleManager
from multiprocess_framework.modules.Logger_module import LoggerManager
from multiprocess_framework.modules.Config_module.config_manager import ConfigManager


# Глобальный класс MockLogger для возможности pickle сериализации
class MockLogger:
    """Мок-логгер для тестов (глобальный класс для pickle)"""
    def info(self, message, module=None):
        pass
    def warning(self, message, module=None):
        pass
    def error(self, message, module=None):
        pass
    def debug(self, message, module=None):
        pass


@pytest.fixture
def mock_logger():
    """Мок-логгер для тестов"""
    return MockLogger()


@pytest.fixture
def console_manager(mock_logger):
    """Фикстура для создания ConsoleManager"""
    return ConsoleManager(logger=mock_logger)


@pytest.fixture
def real_logger():
    """Реальный логгер для интеграционных тестов"""
    config_manager = ConfigManager()
    logger = LoggerManager(config_manager=config_manager)
    logger.initialize()
    return logger


