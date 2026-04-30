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
