"""
ProcessHandle — единый chainable доступ к ресурсам процесса.

Использование:
    handle = srm.for_process("worker")
    handle.queue("system").send(msg)
    handle.event("stop").set()
    handle.status  # → ProcessStatus
"""

from typing import Any, Dict, Optional, TYPE_CHECKING
from multiprocessing import Queue, Event

if TYPE_CHECKING:
    from ..core.shared_resources_manager import SharedResourcesManager
    from ..state.process_data import ProcessData
    from ..types import ProcessStatus


class QueueHandle:
    """
    Обёртка над multiprocessing.Queue с удобными методами.

    Использование:
        handle.queue("system").send(msg)
        data = handle.queue("data").receive(timeout=1.0)
    """

    __slots__ = ("_queue", "_process_name", "_queue_type", "_queue_registry")

    def __init__(
        self,
        queue: Optional[Queue],
        process_name: str,
        queue_type: str,
        queue_registry: Optional[Any] = None,
    ) -> None:
        self._queue = queue
        self._process_name = process_name
        self._queue_type = queue_type
        self._queue_registry = queue_registry

    def send(self, message: Any, timeout: float = 0.0) -> bool:
        """Отправить сообщение в очередь."""
        if self._queue_registry is not None:
            return self._queue_registry.send_to_queue(
                self._process_name, self._queue_type, message, timeout
            )
        if self._queue is None:
            return False
        try:
            if timeout > 0:
                self._queue.put(message, timeout=timeout)
            else:
                self._queue.put_nowait(message)
            return True
        except Exception:
            return False

    def receive(self, timeout: float = 0.0) -> Optional[Any]:
        """Получить сообщение из очереди."""
        if self._queue_registry is not None:
            return self._queue_registry.receive_from_queue(
                self._process_name, self._queue_type, timeout
            )
        if self._queue is None:
            return None
        try:
            return (
                self._queue.get(timeout=timeout)
                if timeout > 0
                else self._queue.get_nowait()
            )
        except Exception:
            return None

    @property
    def size(self) -> int:
        """Текущий размер очереди."""
        if self._queue is None:
            return 0
        try:
            return self._queue.qsize()
        except (NotImplementedError, OSError):
            return 0

    @property
    def is_full(self) -> bool:
        """Очередь заполнена?"""
        return self._queue.full() if self._queue else False

    @property
    def raw(self) -> Optional[Queue]:
        """Low-level доступ к Queue для продвинутых сценариев."""
        return self._queue

    def __repr__(self) -> str:
        return f"QueueHandle('{self._process_name}', '{self._queue_type}')"


class EventHandle:
    """
    Обёртка над multiprocessing.Event с удобными методами.

    Использование:
        handle.event("stop").set()
        handle.event("stop").wait(timeout=5.0)
    """

    __slots__ = ("_event", "_process_name", "_event_name")

    def __init__(
        self,
        event: Optional[Event],
        process_name: str,
        event_name: str,
    ) -> None:
        self._event = event
        self._process_name = process_name
        self._event_name = event_name

    def set(self) -> None:
        """Установить событие."""
        if self._event is not None:
            self._event.set()

    def clear(self) -> None:
        """Сбросить событие."""
        if self._event is not None:
            self._event.clear()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Ожидать событие. Возвращает True если событие установлено."""
        if self._event is None:
            return False
        return self._event.wait(timeout=timeout)

    @property
    def is_set(self) -> bool:
        """Событие установлено?"""
        return self._event.is_set() if self._event else False

    @property
    def raw(self) -> Optional[Event]:
        """Low-level доступ к Event."""
        return self._event

    def __repr__(self) -> str:
        return f"EventHandle('{self._process_name}', '{self._event_name}')"


class ProcessHandle:
    """
    Единый chainable доступ к ресурсам зарегистрированного процесса.

    Использование:
        handle = srm.for_process("worker")
        handle.queue("system").send(msg)
        handle.event("stop").set()
        handle.memory("frame").write(images, index=0)
        handle.status   # → ProcessStatus
        handle.config   # → dict
    """

    __slots__ = ("_name", "_srm")

    def __init__(self, name: str, srm: "SharedResourcesManager") -> None:
        self._name = name
        self._srm = srm

    @property
    def name(self) -> str:
        """Имя процесса."""
        return self._name

    @property
    def data(self) -> Optional["ProcessData"]:
        """ProcessData процесса."""
        return self._srm._process_state_registry.get_process_data(self._name)

    @property
    def status(self) -> Optional["ProcessStatus"]:
        """Текущий статус процесса."""
        pd = self.data
        return pd.status if pd else None

    @property
    def config(self) -> Optional[dict]:
        """Конфиг процесса из ConfigStore."""
        return self._srm._config_store.get(self._name)

    @property
    def metadata(self) -> Dict[str, Any]:
        """Метаданные процесса."""
        pd = self.data
        return pd.metadata if pd else {}

    def queue(self, queue_type: str) -> QueueHandle:
        """Получить handle к очереди процесса."""
        pd = self.data
        raw_queue = pd.get_queue(queue_type) if pd else None
        return QueueHandle(
            queue=raw_queue,
            process_name=self._name,
            queue_type=queue_type,
            queue_registry=self._srm._queue_registry,
        )

    def event(self, event_name: str) -> EventHandle:
        """Получить handle к событию процесса."""
        pd = self.data
        raw_event = pd.get_event(event_name) if pd else None
        return EventHandle(
            event=raw_event,
            process_name=self._name,
            event_name=event_name,
        )

    def memory(self, memory_name: str) -> "MemoryHandle":  # noqa: F821
        """Получить handle к блоку SharedMemory процесса."""
        from .memory_handle import MemoryHandle

        return MemoryHandle(
            memory_manager=self._srm._memory_manager,
            process_name=self._name,
            memory_name=memory_name,
        )

    def __repr__(self) -> str:
        return f"ProcessHandle('{self._name}')"
