"""
SharedResources Module (Refactored) - Менеджер общих ресурсов.

Легковесный контейнер для межпроцессного взаимодействия.
Использует BaseManager + ObservableMixin для единообразия со всеми менеджерами системы.

Архитектура:
- SharedResourcesManager (архив) - легковесный контейнер
- ProcessStateRegistry - реестр состояний процессов (из Process_module)
- EventManager - менеджер событий (BaseManager + ObservableMixin)
- QueueRegistry - реестр очередей (BaseManager + ObservableMixin)
- MemoryManager - менеджер разделенной памяти (BaseManager + ObservableMixin)
- DataSchemaAdapter - адаптер для data_schema модуля
- Интерфейсы - для всех компонентов модуля
"""

from .core.shared_resources_manager import SharedResourcesManager
from .events.event_manager import EventManager, EventType
from .queues.queue_registry import QueueRegistry
from .memory.memory_manager import MemoryManager
from .registry.data_schema_adapter import DataSchemaAdapter

# Интерфейсы
from .core.interfaces import (
    IQueueRegistry,
    IEventManager,
    IMemoryManager,
    IProcessStateRegistry,
    ISharedResourcesManager,
)

__all__ = [
    # Основные классы
    'SharedResourcesManager',
    'EventManager',
    'EventType',
    'QueueRegistry',
    'MemoryManager',
    'DataSchemaAdapter',
    
    # Интерфейсы
    'IQueueRegistry',
    'IEventManager',
    'IMemoryManager',
    'IProcessStateRegistry',
    'ISharedResourcesManager',
    
    # ProcessStateRegistry и ProcessData — импортируй напрямую:
    # from multiprocess_framework.refactored.modules.process_module.state import ...
]

