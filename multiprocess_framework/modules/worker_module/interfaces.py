# -*- coding: utf-8 -*-
"""
Публичные контракты worker_module.

Единственный файл, от которого должны зависеть внешние модули.
Внутренние компоненты модуля используют относительные импорты.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from .types import WorkerStatus, WorkerType


class IWorkerRegistry(ABC):
    """Контракт реестра воркеров."""

    @abstractmethod
    def register(
        self,
        worker_name: str,
        target: Callable,
        config: Any,
        thread: Any,
        stop_event: Any,
        pause_event: Any,
    ) -> bool:
        """Зарегистрировать воркер со статусом ``STOPPED``; ``True`` при успехе.

        Возвращает ``False`` (реестр не меняется), если имя уже занято. ``worker_type`` и
        ``execution_mode`` берутся из ``config`` (по умолчанию APPLICATION и LOOP)."""
        ...

    @abstractmethod
    def unregister(self, worker_name: str) -> bool:
        """Удалить воркер из реестра: ``True`` — удалён, ``False`` — имени не было.

        Поток воркера не останавливается — это делает вызывающий (см. ``remove_worker``)."""
        ...

    @abstractmethod
    def get(self, worker_name: str) -> Optional[Dict]:
        """Запись воркера (dict со статусом, потоком, событиями, метриками) или ``None``, если имени нет.

        Возвращается живая ссылка на внутренний dict, не копия."""
        ...

    @abstractmethod
    def has(self, worker_name: str) -> bool:
        """``True``, если воркер с таким именем зарегистрирован."""
        ...

    @abstractmethod
    def get_all_names(self) -> List[str]:
        """Имена всех зарегистрированных воркеров (новый список, в порядке регистрации)."""
        ...

    @abstractmethod
    def get_by_type(self, worker_type: WorkerType) -> List[str]:
        """Имена воркеров заданного ``WorkerType`` (SYSTEM / APPLICATION); пустой список, если таких нет."""
        ...

    @abstractmethod
    def update_status(self, worker_name: str, status: WorkerStatus) -> None:
        """Установить статус воркера; для незарегистрированного имени — ничего не делает."""
        ...

    @abstractmethod
    def get_status(self, worker_name: str) -> Optional[WorkerStatus]:
        """Текущий ``WorkerStatus`` воркера или ``None``, если имени нет в реестре."""
        ...


class IWorkerLifecycle(ABC):
    """Контракт управления жизненным циклом воркеров."""

    @abstractmethod
    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: Any,
        auto_start: bool = False,
    ) -> bool:
        """Создать воркер (поток не стартует) и зарегистрировать; ``True`` при успехе.

        Args:
            worker_name: уникальное имя воркера.
            target: функция/метод, выполняемые в потоке воркера.
            config: конфигурация воркера (``ThreadConfig``); ``dependencies`` — имена воркеров,
                которые должны быть уже созданы.
            auto_start: сразу запустить воркер после создания.

        Returns:
            ``False``, если имя занято, зависимость не зарегистрирована или (при ``auto_start``)
            не запущена. С ``auto_start=True`` результат — итог ``start_worker``."""
        ...

    @abstractmethod
    def start_worker(self, worker_name: str) -> bool:
        """Запустить воркер; ``True`` при успехе или если он уже ``RUNNING``.

        Если предыдущий поток завершился, создаётся новый поток; повторный запуск
        увеличивает ``restart_count``. ``False`` — воркера нет в реестре."""
        ...

    @abstractmethod
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановить воркер: взвести ``stop_event`` и дождаться завершения потока до ``timeout`` секунд.

        Returns:
            ``True`` — поток завершился (или никогда не запускался), статус ``STOPPED``.
            ``False`` — воркера нет либо поток жив после ``timeout`` (статус остаётся ``STOPPING``)."""
        ...

    @abstractmethod
    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановить и снова запустить воркер; результат — итог ``start_worker``.

        Останавливается только воркер в статусе ``RUNNING``; если остановка не удалась
        (поток завис), новый поток не создаётся и возвращается ``False``. ``False`` и когда
        воркера нет в реестре."""
        ...


class IWorkerManager(ABC):
    """Контракт менеджера потоков.

    Реализуется WorkerManager. Внешние модули (process_module, adapters)
    должны зависеть только от этого интерфейса для обеспечения инверсии зависимостей.

    Методы разделены на категории:
        - Жизненный цикл: initialize/shutdown
        - Создание и управление: create/start/stop/restart/pause/resume
        - Групповые операции: start_all/stop_all
        - Мониторинг: get_status, get_metrics, is_running, has_worker
        - Фильтрация: list_workers (с опциональной фильтрацией по типу)
        - Статистика: get_stats

    Потокобезопасность:
        Все методы потокобезопасны благодаря WorkerRegistry._lock.
        Можно безопасно вызывать из разных потоков одновременно.

    Dict at Boundary:
        create_worker() принимает config как ThreadConfig или dict.
        get_worker_status() возвращает dict, не объект.
    """

    # ---- Жизненный цикл ----

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализировать менеджер (``is_initialized = True``); ``False`` при исключении."""
        ...

    @abstractmethod
    def shutdown(self) -> bool:
        """Остановить все воркеры (``stop_all_workers``) и сбросить ``is_initialized``; ``False`` при исключении."""
        ...

    # ---- Создание и управление ----

    @abstractmethod
    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: Any,
        auto_start: bool = False,
    ) -> bool:
        """Создать воркер (поток не стартует) и зарегистрировать; ``True`` при успехе.

        ``config`` — ``ThreadConfig`` или dict (dict десериализуется через ``ThreadConfig.from_dict``).
        ``False``, если имя занято или зависимость (``config.dependencies``) не зарегистрирована
        либо, при ``auto_start``, не запущена. Результат пишется в лог."""
        ...

    @abstractmethod
    def start_worker(self, worker_name: str) -> bool:
        """Запустить воркер; ``True`` при успехе или если он уже ``RUNNING``, ``False`` — воркера нет."""
        ...

    @abstractmethod
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановить воркер, дождавшись завершения потока до ``timeout`` секунд.

        ``True`` — поток завершён (статус ``STOPPED``); ``False`` — воркера нет или поток жив
        после ``timeout`` (статус остаётся ``STOPPING``). Воркер остаётся в реестре."""
        ...

    @abstractmethod
    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановить (если ``RUNNING``) и запустить воркер заново.

        ``False``, если воркера нет или остановка не удалась за ``timeout`` (новый поток не создаётся)."""
        ...

    @abstractmethod
    def remove_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        """Остановить воркер И убрать из реестра (в отличие от stop_worker).

        Выравнивание контракта под уже существующий публичный метод WorkerManager
        (GUI-delete); не новая возможность. Потребитель — WorkerPoolExecutor
        (chain-пул), пересоздающий воркеров при resize/shutdown без коллизии имён.
        """
        ...

    @abstractmethod
    def pause_worker(self, worker_name: str) -> bool:
        """Поставить воркер на паузу (взвести ``pause_event``); ``False``, если воркера нет.

        Поток не останавливается; пауза действует на следующей проверке в цикле воркера."""
        ...

    @abstractmethod
    def resume_worker(self, worker_name: str) -> bool:
        """Снять паузу воркера (сбросить ``pause_event``); ``False``, если воркера нет."""
        ...

    @abstractmethod
    def drain_worker(self, worker_name: str, *, timeout: float = 5.0, poll: float = 0.005) -> bool:
        """Ф7 G.8: пауза + дождаться завершения текущего кадра (drain перед detach/stop)."""
        ...

    @abstractmethod
    def drain_and_remove(self, worker_name: str, *, timeout: float = 5.0) -> bool:
        """Ф7 G.8: полная последовательность drain→(detach)→stop снятия воркера."""
        ...

    # ---- Групповые операции ----

    @abstractmethod
    def start_all_workers(self) -> None:
        """Запустить все зарегистрированные воркеры (``start_worker`` для каждого)."""
        ...

    @abstractmethod
    def stop_all_workers(self) -> None:
        """Остановить все воркеры параллельно: сначала сигнал всем, затем join с общим дедлайном.

        Реализация ``WorkerManager`` принимает необязательный ``timeout`` (по умолчанию 5.0 с) —
        общий на всех, а не на каждого. Статус каждого воркера по итогу — ``STOPPED``."""
        ...

    @abstractmethod
    def pause_all_workers(self, exclude_system: bool = True) -> None:
        """Поставить на паузу все воркеры.

        При ``exclude_system=True`` воркеры типа ``WorkerType.SYSTEM`` (например heartbeat) пропускаются."""
        ...

    @abstractmethod
    def resume_all_workers(self, exclude_system: bool = True) -> None:
        """Снять паузу со всех воркеров; при ``exclude_system=True`` SYSTEM-воркеры пропускаются."""
        ...

    # ---- Мониторинг ----

    @abstractmethod
    def get_worker_status(self, worker_name: str) -> Optional[Dict]:
        """Статус воркера как dict или ``None``, если воркера нет.

        Ключи: ``name``, ``status``, ``priority``, ``protected``, ``worker_type``, ``execution_mode``,
        ``is_alive``, ``restart_count``, ``last_error``, ``metrics``.
        Если ``target`` — метод объекта с ``get_cycle_metrics()``, его dict добавляется в ответ."""
        ...

    @abstractmethod
    def get_all_workers_status(self) -> Dict[str, Dict]:
        """Словарь ``имя → get_worker_status(имя)`` по всем зарегистрированным воркерам."""
        ...

    @abstractmethod
    def get_worker_metrics(self, worker_name: str) -> Optional[Dict]:
        """Метрики воркера как dict или ``None``, если воркера нет.

        Ключи: ``total_runtime``, ``last_run_duration``, ``successful_runs``, ``failed_runs``,
        ``restart_count``, ``avg_run_time``, ``start_time``, ``uptime``."""
        ...

    @abstractmethod
    def is_worker_running(self, worker_name: str) -> bool:
        """``True``, если воркер зарегистрирован и его статус ``RUNNING``."""
        ...

    @abstractmethod
    def has_worker(self, worker_name: str) -> bool:
        """``True``, если воркер с таким именем зарегистрирован."""
        ...

    @abstractmethod
    def list_workers(self, worker_type: Optional[WorkerType] = None) -> List[str]:
        """Имена воркеров; при заданном ``worker_type`` — только этого типа, иначе все."""
        ...

    # ---- Статистика ----

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Статистика менеджера: базовая (``BaseManager.get_stats``) плюс ``workers_count``, ``system_workers``,
        ``application_workers``, ``running_workers`` и ``workers_status`` (статусы всех воркеров)."""
        ...


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "WorkerStatus",
    "WorkerType",
    "IWorkerRegistry",
    "IWorkerLifecycle",
    "IWorkerManager",
]
