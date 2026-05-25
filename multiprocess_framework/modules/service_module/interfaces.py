"""Публичный контракт service_module — IService Protocol + ServiceLifecycle enum.

Этот файл определяет интерфейс сервиса и его жизненный цикл.
Используется как точка зависимости для ServiceRegistry, scanner, адаптеров.

Правило: НИКАКИХ импортов из Services/, Plugins/, multiprocess_prototype/ —
только stdlib и __future__.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable


class ServiceLifecycle(str, Enum):
    """Жизненный цикл сервиса в ServiceRegistry.

    Допустимые переходы:
        UNREGISTERED -> READY     — после регистрации в Registry
        READY        -> RUNNING   — после успешного start()
        RUNNING      -> STOPPED   — после stop()
        RUNNING      -> ERROR     — исключение в работе
        STOPPED      -> RUNNING   — рестарт (повторный start())
        ERROR        -> READY     — после ручного reset

    Диаграмма состояний::

        UNREGISTERED ──> READY ──> RUNNING ──> STOPPED
                           ^          │            │
                           │          v            │
                           └─── ERROR              │
                           ^                       │
                           └───────────────────────┘
                                  (restart)
    """

    UNREGISTERED = "unregistered"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@runtime_checkable
class IService(Protocol):
    """Protocol для сервиса, совместимого с ServiceRegistry.

    Любой класс, реализующий атрибут ``name: str`` и методы
    ``start``, ``stop``, ``get_status``, автоматически проходит
    ``isinstance(obj, IService)`` без явного наследования
    (structural subtyping).

    Пример::

        class MyService:
            name: str = "my_service"

            def start(self, config: dict) -> bool:
                ...

            def stop(self) -> bool:
                ...

            def get_status(self) -> dict:
                return {"name": self.name, "status": "running"}

        assert isinstance(MyService(), IService)  # True
    """

    name: str

    def start(self, config: dict) -> bool:
        """Запустить сервис с переданной конфигурацией.

        Args:
            config: словарь параметров (содержимое зависит от конкретного сервиса).

        Returns:
            True при успешном запуске, False при ошибке.
        """
        ...

    def stop(self) -> bool:
        """Остановить сервис.

        Returns:
            True при успешной остановке, False при ошибке.
        """
        ...

    def get_status(self) -> dict:
        """Вернуть текущее состояние сервиса.

        Returns:
            Словарь с ключами name, status и прочими метаданными.
        """
        ...
