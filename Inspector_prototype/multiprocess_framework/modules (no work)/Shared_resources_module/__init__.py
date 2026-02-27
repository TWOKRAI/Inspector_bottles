"""
Shared Resources Module - Модуль общих ресурсов для межпроцессного взаимодействия.

Компоненты:
- SharedResourcesManager - главный менеджер общих ресурсов
- ProcessStateRegistry - реестр состояний процессов
- ProcessData - данные процесса (очереди, события, конфигурация)
- QueueManager - менеджер очередей
- EventManager - менеджер событий
- ImageMemoryManager - менеджер разделяемой памяти
- data_schema - универсальная система работы с данными на основе Pydantic v2 (основной модуль)
- data_schema - система работы с данными на основе Pydantic v2

Основная ответственность:
- Межпроцессные ресурсы (Queue, Event, SharedMemory)
- Управление жизненным циклом ресурсов
- Данные компонентов через data_schema модуль
"""

# Основные компоненты Shared Resources
from .SharedResourcesManager import SharedResourcesManager
from .queue_manager import QueueManager
from .Memory_Manager import ImageMemoryManager
# ProcessData и ProcessStateRegistry теперь в Process_module
from ..Process_module.process_state_registry import ProcessStateRegistry
from ..Process_module.process_data import ProcessData, ProcessDataKeys
from .queue_registry import QueueRegistry
from .event_manager import EventManager, EventType

# Data Schema Module - основной модуль на основе Pydantic v2 (рекомендуется)
# Импорт отложен для избежания циклических зависимостей
# Используйте: from multiprocess_framework.modules.Shared_resources_module.data_schema import ...
# или создайте ленивые импорты через __getattr__

__all__ = [
    # Основные компоненты
    'SharedResourcesManager',
    'QueueManager',
    'ImageMemoryManager',
    'ProcessStateRegistry',
    'ProcessData',
    'ProcessDataKeys',
    'QueueRegistry',
    'EventManager',
    'EventType',
    
    # Data Schema Module (Pydantic v2) - модуль для работы с данными
    # Импортируйте напрямую: from .data_schema import DataManager, SchemaRegistry, etc.
    # Или используйте ленивый импорт через __getattr__ (см. ниже)
]


def __getattr__(name: str):
    """
    Ленивый импорт для data_schema модуля для избежания циклических зависимостей.
    
    Позволяет использовать: from ... import DataManager
    без циклических импортов при старте.
    """
    data_schema_exports = {
        'SchemaRegistry',
        'SchemaManager',
        'DataManager',
        'ManagerDataAdapter',
        'DataFactory',
        'BaseComponentModel',
        'BaseManagerModel',
        'ComponentType',
        'DataConverter',
        'DataValidator',
        'FormatType',
        'get_nested_value',
        'set_nested_value',
        'merge_with_defaults',
        'extract_fields',
        'register_schema',
    }
    
    if name in data_schema_exports:
        from .data_schema import (
            SchemaRegistry,
            DataManager,
            ManagerDataAdapter,
            DataFactory,
            BaseComponentModel,
            BaseManagerModel,
            ComponentType,
            DataConverter,
            DataValidator,
            FormatType,
            get_nested_value,
            set_nested_value,
            merge_with_defaults,
            extract_fields,
            register_schema,
        )
        # Добавляем в globals для последующих обращений
        module_exports = {
            'SchemaRegistry': SchemaRegistry,
            'SchemaManager': SchemaRegistry,  # Алиас
            'DataManager': DataManager,
            'ManagerDataAdapter': ManagerDataAdapter,
            'DataFactory': DataFactory,
            'BaseComponentModel': BaseComponentModel,
            'BaseManagerModel': BaseManagerModel,
            'ComponentType': ComponentType,
            'DataConverter': DataConverter,
            'DataValidator': DataValidator,
            'FormatType': FormatType,
            'get_nested_value': get_nested_value,
            'set_nested_value': set_nested_value,
            'merge_with_defaults': merge_with_defaults,
            'extract_fields': extract_fields,
            'register_schema': register_schema,
        }
        globals().update(module_exports)
        return module_exports.get(name)
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

