"""
SharedResources Module — менеджер общих ресурсов для межпроцессного взаимодействия.

Публичный API модуля. Внешние модули импортируют только отсюда.

Быстрый старт:
    srm = SharedResourcesManager()
    srm.initialize()
    srm.register_process("my_process", config_dict)
    # Передать srm в дочерний процесс через pickle
    # В дочернем процессе:
    srm.reinitialize_in_child()
"""

# Основной фасад
from .core.shared_resources_manager import SharedResourcesManager

# Компоненты (для прямого использования)
from .events import EventManager
from .queues import QueueRegistry
from .memory.core import MemoryManager
from .config_store import ConfigStore
from .configs.shared_resources_manager_config import SharedResourcesManagerConfig
from .adapters.data_schema_adapter import DataSchemaAdapter

# Данные процессов
from .state.process_data import ProcessData, ProcessDataKeys, QueuesProxy, EventsProxy
from .state.process_state_registry import ProcessStateRegistry

# Типы
from .types import ProcessStatus, ResourceType, EventType
from .types import ProcessDataDict, QueueConfigDict, MemoryConfigDict

# Интерфейсы
from .core.interfaces import (
    IConfigStore,
    IQueueRegistry,
    IEventManager,
    IMemoryManager,
    IProcessStateRegistry,
    ISharedResourcesManager,
)

__all__ = [
    # Основной фасад
    "SharedResourcesManager",

    # Компоненты
    "EventManager",
    "QueueRegistry",
    "MemoryManager",
    "ConfigStore",
    "SharedResourcesManagerConfig",
    "DataSchemaAdapter",

    # Данные процессов
    "ProcessData",
    "ProcessDataKeys",
    "QueuesProxy",
    "EventsProxy",
    "ProcessStateRegistry",

    # Типы
    "ProcessStatus",
    "ResourceType",
    "EventType",
    "ProcessDataDict",
    "QueueConfigDict",
    "MemoryConfigDict",

    # Интерфейсы
    "IConfigStore",
    "IQueueRegistry",
    "IEventManager",
    "IMemoryManager",
    "IProcessStateRegistry",
    "ISharedResourcesManager",
]
