"""
Конфигурация pytest для тестов Shared_resources_module.
"""
import pytest
from multiprocessing import Queue, Event

from multiprocess_framework.modules.Shared_resources_module import (
    SharedResourcesManager,
    ProcessData,
    ProcessStateRegistry,

)


@pytest.fixture
def shared_resources():
    """Создает экземпляр SharedResourcesManager для тестов."""
    return SharedResourcesManager()


@pytest.fixture
def process_state_registry():
    """Создает экземпляр ProcessStateRegistry для тестов."""
    return ProcessStateRegistry()


@pytest.fixture
def sample_queue():
    """Создает тестовую очередь."""
    return Queue()


@pytest.fixture
def sample_event():
    """Создает тестовое событие."""
    return Event()


@pytest.fixture
def sample_config():
    """Создает тестовую конфигурацию процесса."""
    config = None
    config.update_process_config(key1="value1", key2="value2")
    config.update_manager_config("test_manager", {"setting": "value"})
    return config


@pytest.fixture
def sample_process_data(sample_config, sample_queue, sample_event):
    """Создает тестовый ProcessData."""
    process_data = ProcessData(
        name="test_process",
        _queues_dict={"data": sample_queue, "system": Queue()},
        _events_dict={"start": sample_event, "stop": Event()},
        config=sample_config,
        status="running"
    )
    return process_data

