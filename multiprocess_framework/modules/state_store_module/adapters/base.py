"""base.py -- IStateAdapter Protocol + StateAdapterBase ABC.

IStateAdapter -- runtime_checkable Protocol, определяющий минимальный контракт
для адаптеров, связывающих доменную логику с реактивным деревом состояния
(StateProxy / GuiStateProxy).

StateAdapterBase -- абстрактный базовый класс (не BaseManager: адаптер -- легковесная
обёртка, а не полноценный менеджер процесса). Предоставляет:
    - lifecycle: bind / unbind / connect / disconnect
    - anti-loop защиту через _pending_paths (паттерн из RegistersStateAdapter)
    - инжектируемые managers (logger, stats, error) с silent fallback
    - шаблонный метод _subscribe_all / _unsubscribe_all для наследников

Refs: ADR plans/prototype-skeleton-2026-05/phase-0-foundation.md Task 0.2
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from multiprocess_framework.modules.state_store_module.interfaces import IStateProxy


# ---------------------------------------------------------------------------
# Protocol -- утиная типизация для isinstance-проверок
# ---------------------------------------------------------------------------


@runtime_checkable
class IStateAdapter(Protocol):
    """Минимальный контракт адаптера StateStore.

    Любой объект, реализующий эти 5 методов/свойств, считается адаптером.
    runtime_checkable позволяет isinstance(obj, IStateAdapter) без наследования.

    Методы:
        bind    -- привязать адаптер к StateProxy
        unbind  -- отвязать адаптер от StateProxy
        sync_domain_to_state  -- записать текущее состояние домена в StateStore
        sync_state_to_domain  -- прочитать состояние из StateStore в домен

    Свойства:
        is_bound  -- True если адаптер привязан к StateProxy
    """

    def bind(self, state_proxy: IStateProxy) -> None:
        """Привязать адаптер к StateProxy."""
        ...

    def unbind(self) -> None:
        """Отвязать адаптер от StateProxy и очистить подписки."""
        ...

    def sync_domain_to_state(self) -> None:
        """Синхронизировать доменные данные -> StateStore."""
        ...

    def sync_state_to_domain(self) -> None:
        """Синхронизировать StateStore -> доменные данные."""
        ...

    @property
    def is_bound(self) -> bool:
        """True если адаптер привязан к StateProxy."""
        ...


# ---------------------------------------------------------------------------
# ABC -- базовый класс для конкретных адаптеров
# ---------------------------------------------------------------------------


class StateAdapterBase(ABC):
    """Абстрактный базовый класс для адаптеров StateStore.

    Не наследует BaseManager -- адаптер lightweight, не полный менеджер процесса.
    Все managers (logger, stats, error) инжектируются через конструктор.

    Паттерн anti-loop:
        _pending_paths хранит пути, для которых адаптер сам инициировал set().
        При получении эхо-дельты от StateProxy адаптер проверяет _pending_paths
        и пропускает обратную синхронизацию, предотвращая зацикливание.
        (Паттерн извлечён из RegistersStateAdapter в backup.)

    Lifecycle:
        1. adapter = ConcreteAdapter(logger=..., stats=...)
        2. adapter.bind(state_proxy)      -- привязать к прокси
        3. adapter.connect()              -- подписаться на изменения
        4. adapter.sync_state_to_domain() -- начальная синхронизация
        ...работа...
        5. adapter.disconnect()           -- отписаться
        6. adapter.unbind()               -- отвязать от прокси

    Наследники обязаны реализовать:
        _subscribe_all()    -- создать подписки при connect()
        _unsubscribe_all()  -- отменить подписки при disconnect()
        sync_domain_to_state()
        sync_state_to_domain()
    """

    def __init__(
        self,
        state_proxy: IStateProxy | None = None,
        logger: Any | None = None,
        stats: Any | None = None,
        error: Any | None = None,
    ) -> None:
        """Инициализация адаптера.

        Args:
            state_proxy: StateProxy или GuiStateProxy (опционален, можно bind() позже).
            logger: менеджер логирования (LoggerManager или совместимый).
                    Если None -- методы _log_* молча ничего не делают.
            stats: менеджер статистики (StatisticsManager или совместимый).
            error: менеджер ошибок (ErrorManager или совместимый).
        """
        # Прокси для связи с StateStore
        self._proxy: IStateProxy | None = state_proxy
        # Состояние подключения (connect/disconnect)
        self._connected: bool = False
        # ID подписок (для отписки при disconnect)
        self._sub_ids: list[str] = []
        # Anti-loop: пути, для которых мы инициировали set и ждём эхо
        self._pending_paths: set[str] = set()

        # Инжектируемые managers (опциональные)
        self._logger = logger
        self._stats = stats
        self._error = error

    # -------------------------------------------------------------------
    # IStateAdapter -- публичный API
    # -------------------------------------------------------------------

    def bind(self, state_proxy: IStateProxy) -> None:
        """Привязать адаптер к StateProxy.

        Если адаптер уже подключён (connect) -- сначала отключается.
        Старый прокси заменяется новым.

        Args:
            state_proxy: экземпляр StateProxy / GuiStateProxy.
        """
        if self._connected:
            self.disconnect()
        self._proxy = state_proxy
        self._log_info("bind: привязан к StateProxy")

    def unbind(self) -> None:
        """Отвязать адаптер от StateProxy.

        Отключает подписки (если подключён) и убирает ссылку на прокси.
        """
        if self._connected:
            self.disconnect()
        self._proxy = None
        self._log_info("unbind: отвязан от StateProxy")

    @property
    def is_bound(self) -> bool:
        """True если адаптер привязан к StateProxy (proxy != None)."""
        return self._proxy is not None

    @property
    def is_connected(self) -> bool:
        """True если адаптер подключён (connect() вызван, disconnect() -- нет)."""
        return self._connected

    @property
    def pending_paths(self) -> frozenset[str]:
        """Текущие pending-пути (для тестирования/отладки)."""
        return frozenset(self._pending_paths)

    # -------------------------------------------------------------------
    # Lifecycle -- шаблонный метод (Template Method)
    # -------------------------------------------------------------------

    def connect(self) -> None:
        """Подключить адаптер: создать подписки на StateProxy.

        Вызывает abstract _subscribe_all() в наследнике.
        Игнорируется если уже подключён или не привязан к прокси.
        """
        if self._connected:
            self._log_warning("connect: уже подключён, повторный вызов игнорируется")
            return
        if self._proxy is None:
            self._log_warning("connect: нет привязанного StateProxy, вызовите bind() сначала")
            return

        self._subscribe_all()
        self._connected = True
        self._log_info("connect: подключён, подписок=%d", len(self._sub_ids))

    def disconnect(self) -> None:
        """Отключить адаптер: отменить подписки на StateProxy.

        Вызывает abstract _unsubscribe_all() в наследнике.
        Очищает pending_paths и sub_ids.
        """
        if not self._connected:
            self._log_warning("disconnect: не подключён, вызов игнорируется")
            return

        self._unsubscribe_all()
        self._pending_paths.clear()
        self._sub_ids.clear()
        self._connected = False
        self._log_info("disconnect: отключён")

    # -------------------------------------------------------------------
    # Anti-loop helpers -- для наследников
    # -------------------------------------------------------------------

    def _mark_pending(self, path: str) -> None:
        """Пометить путь как pending (мы инициировали изменение, ждём эхо).

        Args:
            path: путь в StateStore, для которого мы вызвали set().
        """
        self._pending_paths.add(path)

    def _check_and_clear_pending(self, path: str) -> bool:
        """Проверить и снять pending-флаг для пути.

        Возвращает True если путь был pending (эхо -- нужно пропустить).
        Возвращает False если путь не был pending (внешнее изменение -- обработать).

        Args:
            path: путь из полученной дельты.

        Returns:
            True если это эхо нашего собственного изменения.
        """
        if path in self._pending_paths:
            self._pending_paths.discard(path)
            return True
        return False

    # -------------------------------------------------------------------
    # Абстрактные методы -- наследник реализует
    # -------------------------------------------------------------------

    @abstractmethod
    def _subscribe_all(self) -> None:
        """Создать все необходимые подписки на StateProxy.

        Наследник должен:
        1. Вызвать self._proxy.subscribe(...) для нужных паттернов.
        2. Сохранить возвращённые sub_id в self._sub_ids.
        """
        ...

    @abstractmethod
    def _unsubscribe_all(self) -> None:
        """Отменить все подписки на StateProxy.

        Типовая реализация в наследнике::

            for sub_id in self._sub_ids:
                self._proxy.unsubscribe(sub_id)
        """
        ...

    @abstractmethod
    def sync_domain_to_state(self) -> None:
        """Синхронизировать текущее доменное состояние -> StateStore.

        Наследник записывает свои данные в StateProxy через set()/merge().
        """
        ...

    @abstractmethod
    def sync_state_to_domain(self) -> None:
        """Синхронизировать StateStore -> доменное состояние.

        Наследник читает данные из StateProxy через get() и обновляет
        свои внутренние структуры.
        """
        ...

    # -------------------------------------------------------------------
    # Логирование -- silent fallback если logger не передан
    # -------------------------------------------------------------------

    def _log_info(self, msg: str, *args: Any) -> None:
        """Логировать info-сообщение через инжектированный logger.

        Если logger=None -- молча ничего не делает (silent fallback).
        """
        if self._logger is not None:
            self._logger.log_info(msg % args if args else msg)

    def _log_warning(self, msg: str, *args: Any) -> None:
        """Логировать warning-сообщение через инжектированный logger."""
        if self._logger is not None:
            self._logger.log_warning(msg % args if args else msg)

    def _log_error(self, msg: str, *args: Any) -> None:
        """Логировать error-сообщение через инжектированный logger."""
        if self._logger is not None:
            self._logger.log_error(msg % args if args else msg)


__all__ = ["IStateAdapter", "StateAdapterBase"]
