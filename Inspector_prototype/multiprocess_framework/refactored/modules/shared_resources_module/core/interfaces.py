"""
Интерфейсы (публичный контракт) для shared_resources_module.

Единственный файл, от которого зависят внешние модули.
Использует Any вместо конкретных типов multiprocessing/numpy для pickle-safety
и отсутствия тяжёлых зависимостей в интерфейсном слое.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# IConfigStore
# ---------------------------------------------------------------------------

class IConfigStore(ABC):
    """Pickle-safe хранилище конфигов всех процессов."""

    @abstractmethod
    def store(self, name: str, config: dict) -> None:
        """Сохранить конфиг процесса."""

    @abstractmethod
    def get(self, name: str) -> Optional[dict]:
        """Получить конфиг процесса."""

    @abstractmethod
    def get_all(self) -> Dict[str, dict]:
        """Получить все конфиги."""

    @abstractmethod
    def has(self, name: str) -> bool:
        """Проверить наличие конфига."""

    @abstractmethod
    def remove(self, name: str) -> bool:
        """Удалить конфиг процесса."""


# ---------------------------------------------------------------------------
# IQueueRegistry
# ---------------------------------------------------------------------------

class IQueueRegistry(ABC):
    """Управление очередями: создание, доступ, рассылка."""

    @abstractmethod
    def create_queues(
        self,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Создать очереди по конфигурации."""

    @abstractmethod
    def create_and_register_queues(
        self,
        process_name: str,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Создать и зарегистрировать очереди для процесса."""

    @abstractmethod
    def register_process_queues(
        self,
        process_name: str,
        queues: Dict[str, Any],
    ) -> bool:
        """Зарегистрировать уже созданные очереди."""

    @abstractmethod
    def get_queue(self, process_name: str, queue_type: str) -> Optional[Any]:
        """Получить очередь процесса."""

    @abstractmethod
    def send_to_queue(
        self,
        process_name: str,
        queue_type: str,
        message: Any,
    ) -> bool:
        """Отправить сообщение в очередь."""

    @abstractmethod
    def broadcast_message(
        self,
        message: Any,
        queue_type: str = "system",
        exclude_process: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам. Возвращает кол-во доставок."""

    @abstractmethod
    def get_queue_sizes(self) -> Dict[str, Dict[str, int]]:
        """Получить размеры всех очередей."""


# ---------------------------------------------------------------------------
# IEventManager
# ---------------------------------------------------------------------------

class IEventManager(ABC):
    """Системные события: emit, subscribe, wait, reinitialize."""

    @abstractmethod
    def emit_event(
        self,
        event_type: Any,
        process_name: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Отправить событие."""

    @abstractmethod
    def subscribe(self, event_type: Any, callback: Callable) -> bool:
        """Подписаться на события."""

    @abstractmethod
    def wait_for_event(
        self,
        event_type: Optional[Any] = None,
        timeout: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        """Ожидать событие с таймаутом."""

    @abstractmethod
    def reinitialize(self) -> bool:
        """Пересоздать non-pickle ресурсы после unpickle в дочернем процессе."""


# ---------------------------------------------------------------------------
# IMemoryManager
# ---------------------------------------------------------------------------

class IMemoryManager(ABC):
    """Управление SharedMemory: owner/consumer паттерн, pickle-safe через имена."""

    @abstractmethod
    def create_memory_dict(
        self,
        process_name: str,
        memory_names: Dict[str, tuple],
        coll: int,
    ) -> bool:
        """Создать блоки SharedMemory для процесса (owner)."""

    @abstractmethod
    def get_memory_data(
        self,
        process_name: str,
        memory_name: str,
    ) -> Optional[Dict]:
        """Получить метаданные блока памяти."""

    @abstractmethod
    def write_images(
        self,
        process_name: str,
        memory_name: str,
        images: List[Any],
        index: int,
        pack_fast: bool = True,
    ) -> Optional[str]:
        """
        Записать изображения в SharedMemory.

        pack_fast: True — np.copyto (быстрее). False — tobytes (legacy, совместимость).
        """

    @abstractmethod
    def read_images(
        self,
        process_name: str,
        memory_name: str,
        index: int,
        n: int = -1,
        copy: bool = True,
    ) -> Optional[List[Any]]:
        """
        Прочитать изображения из SharedMemory.

        copy: True — копии (безопасно). False — view (быстрее, использовать до следующей записи).
        """

    @abstractmethod
    def release_memory(
        self, process_name: str, memory_name: str, index: int
    ) -> None:
        """Освободить слот памяти."""

    @abstractmethod
    def close_memory(self, process_name: str, memory_name: str) -> None:
        """Закрыть и очистить блок памяти."""

    @abstractmethod
    def reinitialize_handles(self) -> bool:
        """Открыть SharedMemory по именам после unpickle (consumer)."""


# ---------------------------------------------------------------------------
# IProcessStateRegistry
# ---------------------------------------------------------------------------

class IProcessStateRegistry(ABC):
    """Реестр runtime-состояний процессов: Dict[str, ProcessData]."""

    @abstractmethod
    def register_process(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        config: Optional[Any] = None,
    ) -> bool:
        """Зарегистрировать процесс."""

    @abstractmethod
    def has_process(self, process_name: str) -> bool:
        """Проверить наличие процесса."""

    @abstractmethod
    def unregister_process(self, process_name: str) -> bool:
        """Удалить процесс из реестра."""

    @abstractmethod
    def get_process_data(self, process_name: str) -> Optional[Any]:
        """Получить ProcessData процесса."""

    @abstractmethod
    def get_all_process_data(self) -> Dict[str, Any]:
        """Получить все ProcessData."""

    @abstractmethod
    def get_process_names(self) -> List[str]:
        """Список всех зарегистрированных процессов."""

    @abstractmethod
    def update_state(
        self,
        process_name: str,
        status: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Обновить состояние процесса."""

    @abstractmethod
    def add_queue(
        self,
        process_name: str,
        queue_type: str,
        queue: Any,
    ) -> bool:
        """Добавить очередь в ProcessData процесса."""

    @abstractmethod
    def add_event(
        self,
        process_name: str,
        event_name: str,
        event: Any,
    ) -> bool:
        """Добавить событие в ProcessData процесса."""


# ---------------------------------------------------------------------------
# ISharedResourcesManager
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
