"""
Интерфейсы (публичный контракт) для shared_resources_module.

ISharedResourcesManager определён здесь (фасад).
Остальные интерфейсы — в своих подмодулях, реэкспортируются для удобства.
Внешние модули могут импортировать из core.interfaces или из подмодулей.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

# Импорт из подмодулей (co-location: интерфейс рядом с реализацией)
from ..config_store import IConfigStore
from ..state.interfaces import IProcessStateRegistry
from ..queues.interfaces import IQueueRegistry
from ..events.interfaces import IEventManager
from ..memory.interfaces import IMemoryManager


# ---------------------------------------------------------------------------
# ISharedResourcesManager (фасад — остаётся в core)
# ---------------------------------------------------------------------------

class ISharedResourcesManager(ABC):
    """
    Фасад-делегатор для всех общих ресурсов системы.

    Единая точка регистрации процессов и доступа к их ресурсам.
    Pickle-safe: передаётся напрямую в дочерние процессы.
    """

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализировать SRM и все внутренние менеджеры."""

    @abstractmethod
    def shutdown(self) -> bool:
        """Завершить работу SRM."""

    @abstractmethod
    def register_process(self, name: str, config: dict) -> bool:
        """
        Единая точка регистрации процесса.

        Создаёт ConfigStore запись, ProcessData, очереди, события, SharedMemory.
        """

    @abstractmethod
    def reinitialize_in_child(self) -> bool:
        """Восстановить non-pickle ресурсы после unpickle в дочернем процессе."""

    @abstractmethod
    def get_process_data(self, process_name: str) -> Optional[Any]:
        """Получить ProcessData процесса."""

    @abstractmethod
    def get_all_process_data(self) -> Dict[str, Any]:
        """Получить все ProcessData."""

    @abstractmethod
    def get_process_config(self, name: str) -> Optional[dict]:
        """Получить конфиг процесса из ConfigStore."""

    @abstractmethod
    def get_process_names(self) -> List[str]:
        """Список всех зарегистрированных процессов."""

    @abstractmethod
    def for_process(self, name: str) -> Any:
        """Получить ProcessHandle — единый доступ к ресурсам процесса (не `process`: см. BaseManager.process)."""

    @abstractmethod
    def has_process(self, name: str) -> bool:
        """Проверить, зарегистрирован ли процесс."""

    @abstractmethod
    def broadcast(
        self,
        message: Any,
        queue_type: str = "system",
        exclude: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам."""

    @abstractmethod
    def get_all_statuses(self) -> Dict[str, Any]:
        """Получить статусы всех процессов."""

    # Properties — доступ к внутренним менеджерам

    @property
    @abstractmethod
    def config_store(self) -> IConfigStore:
        """Хранилище конфигов."""

    @property
    @abstractmethod
    def process_state_registry(self) -> IProcessStateRegistry:
        """Реестр runtime-состояний."""

    @property
    @abstractmethod
    def queue_registry(self) -> IQueueRegistry:
        """Реестр очередей."""

    @property
    @abstractmethod
    def event_manager(self) -> IEventManager:
        """Менеджер системных событий."""

    @property
    @abstractmethod
    def memory_manager(self) -> IMemoryManager:
        """Менеджер SharedMemory."""


# ---------------------------------------------------------------------------
# Re-export для обратной совместимости (внешние импортируют из core.interfaces)
# ---------------------------------------------------------------------------

__all__ = [
    "IConfigStore",
    "IProcessStateRegistry",
    "IQueueRegistry",
    "IEventManager",
    "IMemoryManager",
    "ISharedResourcesManager",
]
