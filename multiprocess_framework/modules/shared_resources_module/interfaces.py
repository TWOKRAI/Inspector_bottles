# Реэкспорт публичных интерфейсов модуля.
# Внешние модули импортируют интерфейсы отсюда.
from .core.interfaces import (  # noqa: F401
    IConfigStore,
    IQueueRegistry,
    IEventManager,
    IMemoryManager,
    IProcessStateRegistry,
    ISharedResourcesManager,
)


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "IConfigStore",
    "IQueueRegistry",
    "IEventManager",
    "IMemoryManager",
    "IProcessStateRegistry",
    "ISharedResourcesManager",
]
