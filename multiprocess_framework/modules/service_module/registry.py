"""ServiceRegistry — singleton-реестр long-running сервисов.

Центральный каталог: хранит *классы* сервисов (не экземпляры).
Инстанцирование — ответственность application-слоя при вызове start().

Регистрация через декоратор::

    @register_service(name="webcam_camera", meta={"vendor": "opencv"})
    class WebcamCameraService:
        name: str = "webcam_camera"
        def start(self, config: dict) -> bool: ...
        def stop(self) -> bool: ...
        def get_status(self) -> dict: ...

Доступ к каталогу::

    registry = ServiceRegistry()   # всегда тот же экземпляр (singleton)
    registry.list()                # все записи
    registry.get("webcam_camera")  # одна запись или None
    registry.filter(ServiceLifecycle.RUNNING)  # по lifecycle

Правило: НИКАКИХ импортов из Services/, Plugins/, multiprocess_prototype/ —
только stdlib + interfaces.py (service_module).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .interfaces import ServiceLifecycle


@dataclass
class ServiceEntry:
    """Запись о сервисе в реестре.

    Attributes:
        name:      Уникальное имя сервиса (ключ в реестре).
        cls:       Класс сервиса (реализует IService Protocol).
        lifecycle: Текущее состояние жизненного цикла.
        meta:      Произвольные метаданные (vendor, version и т.п.).
    """

    name: str
    cls: type
    lifecycle: ServiceLifecycle = ServiceLifecycle.UNREGISTERED
    meta: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"<ServiceEntry '{self.name}' cls={self.cls.__name__} lifecycle={self.lifecycle.value}>"


class ServiceRegistry:
    """Singleton-реестр сервисов с thread-safe доступом.

    Гарантирует единственный экземпляр через ``__new__``.
    Все мутирующие операции (register/unregister/clear)
    защищены ``threading.Lock``.
    """

    _instance: ServiceRegistry | None = None
    _init_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> ServiceRegistry:
        """Потокобезопасное создание singleton."""
        if cls._instance is None:
            with cls._init_lock:
                # Double-checked locking
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._registry: dict[str, ServiceEntry] = {}
                    instance._lock = threading.Lock()
                    cls._instance = instance
        return cls._instance

    # ------------------------------------------------------------------
    # Мутирующие операции (под lock)
    # ------------------------------------------------------------------

    def register(self, entry: ServiceEntry) -> None:
        """Зарегистрировать сервис в реестре.

        Args:
            entry: Запись ServiceEntry с уникальным именем.

        Raises:
            ValueError: Если сервис с таким именем уже зарегистрирован.
        """
        with self._lock:
            if entry.name in self._registry:
                existing = self._registry[entry.name]
                raise ValueError(
                    f"Сервис '{entry.name}' уже зарегистрирован: "
                    f"{existing.cls.__module__}.{existing.cls.__qualname__}. "
                    f"Попытка перезаписать: "
                    f"{entry.cls.__module__}.{entry.cls.__qualname__}"
                )
            self._registry[entry.name] = entry

    def unregister(self, name: str) -> bool:
        """Удалить сервис из реестра по имени.

        Args:
            name: Имя сервиса для удаления.

        Returns:
            True если сервис был удалён, False если не найден.
        """
        with self._lock:
            if name in self._registry:
                del self._registry[name]
                return True
            return False

    def clear(self) -> None:
        """Очистить реестр (для изоляции тестов)."""
        with self._lock:
            self._registry.clear()

    # ------------------------------------------------------------------
    # Читающие операции (под lock для консистентности snapshot)
    # ------------------------------------------------------------------

    def get(self, name: str) -> ServiceEntry | None:
        """Получить запись сервиса по имени.

        Args:
            name: Имя сервиса.

        Returns:
            ServiceEntry или None если не найден.
        """
        with self._lock:
            return self._registry.get(name)

    def list(self) -> list[ServiceEntry]:
        """Все зарегистрированные сервисы (копия списка).

        Returns:
            Список ServiceEntry (безопасен для итерации
            при параллельной модификации реестра).
        """
        with self._lock:
            return list(self._registry.values())

    def filter(self, lifecycle: ServiceLifecycle) -> list[ServiceEntry]:
        """Сервисы в указанном состоянии lifecycle.

        Args:
            lifecycle: Состояние для фильтрации.

        Returns:
            Копия списка (безопасна для итерации при модификации реестра).
        """
        with self._lock:
            return [entry for entry in self._registry.values() if entry.lifecycle == lifecycle]

    # ------------------------------------------------------------------
    # Dunder-методы
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._registry)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._registry

    def __repr__(self) -> str:
        with self._lock:
            count = len(self._registry)
        return f"<ServiceRegistry services={count}>"


def register_service(
    name: str | None = None,
    meta: dict | None = None,
):
    """Декоратор для регистрации класса сервиса в глобальном ServiceRegistry.

    Если ``name`` не задан, берёт ``cls.name`` (атрибут класса).
    Lifecycle при регистрации через декоратор — ``READY``
    (сервис готов к запуску, но ещё не запущен).

    Использование::

        @register_service(name="my_service", meta={"version": "1.0"})
        class MyService:
            name: str = "my_service"
            def start(self, config: dict) -> bool: ...
            def stop(self) -> bool: ...
            def get_status(self) -> dict: ...

    Или с автоматическим именем из ``cls.name``::

        @register_service()
        class MyService:
            name: str = "my_service"
            ...

    Args:
        name: Явное имя сервиса (приоритет над ``cls.name``).
        meta: Произвольные метаданные для ServiceEntry.

    Raises:
        ValueError: Если ``name`` не задан и у класса нет атрибута ``name``.
        ValueError: Если сервис с таким именем уже зарегистрирован.
    """

    def decorator(cls: type) -> type:
        resolved_name = name or getattr(cls, "name", None)
        if not resolved_name:
            raise ValueError(
                f"@register_service: класс {cls.__name__} не имеет атрибута 'name' и аргумент name не передан"
            )
        entry = ServiceEntry(
            name=resolved_name,
            cls=cls,
            lifecycle=ServiceLifecycle.READY,
            meta=meta or {},
        )
        ServiceRegistry().register(entry)
        return cls

    return decorator
