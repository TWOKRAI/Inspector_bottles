"""
Конфигурация pytest для тестов Logger_module.

Общие фикстуры для всех тестов модуля.
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock

from multiprocess_framework.modules.Logger_module import (
    LoggerManager,
    LogConfig,
    LogLevel,
    LogScope,
    ChannelConfig,
    ScopeConfig
)


@pytest.fixture
def temp_dir():
    """Фикстура для временной директории"""
    temp_dir = tempfile.mkdtemp()
    log_dir = Path(temp_dir) / "logs"
    log_dir.mkdir(exist_ok=True)
    
    yield temp_dir
    
    # Очистка после теста
    # Пытаемся закрыть все открытые файлы перед удалением
    import gc
    gc.collect()
    
    if Path(temp_dir).exists():
        try:
            shutil.rmtree(temp_dir)
        except PermissionError:
            # На Windows файлы могут быть заблокированы
            # Пробуем удалить через некоторое время
            import time
            time.sleep(0.1)
            try:
                shutil.rmtree(temp_dir)
            except PermissionError:
                # Если все еще не получается, просто пропускаем
                pass


@pytest.fixture
def log_config(temp_dir):
    """Фикстура для базовой конфигурации логирования"""
    config = LogConfig()
    config.app_name = "test_app"
    
    # Добавляем консольный канал
    config.channels['console'] = ChannelConfig(
        name='console',
        type='console',
        enabled=True
    )
    
    # Добавляем файловый канал
    log_dir = Path(temp_dir) / "logs"
    log_file = log_dir / "test.log"
    config.channels['file'] = ChannelConfig(
        name='file',
        type='file',
        enabled=True,
        file_path=str(log_file)
    )
    
    # Настраиваем область SYSTEM
    config.scopes[LogScope.SYSTEM] = ScopeConfig(
        scope=LogScope.SYSTEM,
        enabled=True,
        min_level=LogLevel.DEBUG,
        channels=['console', 'file']
    )
    
    return config


@pytest.fixture
def logger_manager(log_config):
    """Фикстура для LoggerManager"""
    logger = LoggerManager(config=log_config)
    yield logger
    # Закрываем все каналы перед shutdown
    logger.flush()
    # Закрываем файловые каналы
    for channel in list(logger.channels.values()) + list(logger._module_channels.values()):
        if hasattr(channel, 'close'):
            try:
                channel.close()
            except Exception:
                pass
    logger.shutdown()


@pytest.fixture
def mock_process():
    """Фикстура для mock процесса"""
    process = Mock()
    process.name = "test_process"
    return process


@pytest.fixture
def logger_adapter(log_config, mock_process):
    """Фикстура для LoggerAdapter"""
    logger_manager = LoggerManager(config=log_config)
    logger_manager.initialize()
    
    from multiprocess_framework.modules.Logger_module import LoggerAdapter
    adapter = LoggerAdapter(logger_manager, mock_process)
    
    yield adapter
    
    logger_manager.shutdown()


@pytest.fixture
def batch_config():
    """Фикстура для BatchConfig"""
    from multiprocess_framework.modules.Logger_module.batcher import BatchConfig
    return BatchConfig(
        max_size=5,
        flush_interval=0.1,
        priority_flush=True
    )


@pytest.fixture
def flush_callback():
    """Фикстура для mock callback батчера"""
    return Mock()

