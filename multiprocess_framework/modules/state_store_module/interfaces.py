"""interfaces.py — Публичные контракты state_store_module.

Контракты двух типов (ADR-SS-009):

    IRouter (Protocol)          — внешняя зависимость (RouterManager), утиная типизация (ADR-SS-001)
    IStateStore (ABC)           — контракт TreeStore (серверное дерево состояния)
    IStateProxy (ABC)           — контракт StateProxy (клиентский прокси)
    IStateStoreManager (ABC)    — контракт StateStoreManager (серверный фасад)

Карта: какой контракт когда использовать
-----------------------------------------
    IRouter         — передавать в __init__ StateProxy, StateStoreManager, DeltaDispatcher
                      вместо конкретного RouterManager. RouterManager уже реализует
                      этот Protocol без изменений (ADR-SS-001).

    IStateStore     — тип аннотации для TreeStore в менеджере, тестах и селекторах.
                      TreeStore наследует IStateStore явно (задача 2.1.1, ADR-SS-009).

    IStateProxy     — тип аннотации для StateProxy/GuiStateProxy в app-коде и тестах.
                      StateProxy наследует IStateProxy явно (задача 2.1.3, ADR-SS-009).

    IStateStoreManager — тип аннотации для StateStoreManager в ProcessManagerProcess.
                         StateStoreManager наследует IStateStoreManager (задача 2.1.3, ADR-SS-009).

Правило: внешние модули импортируют только из interfaces.py, не из внутренних подпакетов.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from multiprocess_framework.modules.state_store_module.core.delta import Delta


# ---------------------------------------------------------------------------
# Внешняя зависимость — Protocol (утиная типизация, ADR-SS-001)
# RouterManager уже реализует этот контракт без изменений.
# ---------------------------------------------------------------------------

@runtime_checkable
class IRouter(Protocol):
    """Минимальный контракт Router для state_store_module.

    Не импортировать RouterManager напрямую — только через этот Protocol.
    RouterManager прототипа/фреймворка реализует все три метода (ADR-SS-001).

    Используется в:
        StateProxy.__init__(router: IRouter | None)
        StateStoreManager.__init__(router: IRouter | None)
        DeltaDispatcher.__init__(router: IRouter | None)
    """

    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
    ) -> None:
        """Зарегистрировать handler на IPC-команду."""
        ...

    def send_async(self, message: dict, priority: str = "normal") -> None:
        """Fire-and-forget отправка сообщения (async, без ожидания ответа)."""
        ...

    def send(self, message: dict) -> dict | None:
        """Синхронная отправка сообщения с ожиданием ответа."""
        ...


# ---------------------------------------------------------------------------
# Собственные публичные классы — ABC (ADR-SS-009)
# Точные сигнатуры соответствуют существующим реализациям в прототипе.
# ---------------------------------------------------------------------------

class IStateStore(ABC):
    """Контракт TreeStore — серверное иерархическое дерево состояния.

    TreeStore наследует IStateStore явно в задаче 2.1.1.
    Используется как тип аннотации в StateStoreManager, DeltaDispatcher,
    Selector и тестах.

    ADR-SS-009: ABC выбран потому что TreeStore — собственный публичный класс
    фреймворка (в отличие от RouterManager — внешней зависимости).
    """

    @abstractmethod
    def get(self, path: str, default: Any = None) -> Any:
        """Получить значение по точечному пути.

        Args:
            path: точечный путь к узлу, например 'cameras.0.config.fps'.
            default: значение по умолчанию если путь не существует.

        Returns:
            Значение из дерева или default.

        Raises:
            KeyError: если путь не существует и default не передан.
        """
        ...

    @abstractmethod
    def get_subtree(self, path: str) -> dict:
        """Получить поддерево как deep-copy dict.

        Args:
            path: путь к поддереву. Пустая строка — всё дерево.

        Returns:
            dict — изолированная копия поддерева.
        """
        ...

    @abstractmethod
    def set(self, path: str, value: Any, source: str = "") -> "Delta | None":
        """Установить значение по пути.

        Автоматически создаёт промежуточные узлы.

        Args:
            path: точечный путь (непустой).
            value: новое значение (должно быть pickle-совместимым).
            source: строка-источник изменения (для Delta).

        Returns:
            Delta если значение изменилось, None если значение не изменилось.
        """
        ...

    @abstractmethod
    def merge(self, path: str, data: dict, source: str = "") -> "list[Delta]":
        """Глубокий merge dict в поддерево.

        Dict'ы мержатся рекурсивно, скаляры перезаписываются.

        Args:
            path: путь к поддереву (может быть пустым — мерж в корень).
            data: данные для мержа.
            source: источник изменения.

        Returns:
            Список Delta — по одной на каждое изменившееся значение.
        """
        ...

    @abstractmethod
    def delete(self, path: str, source: str = "") -> "Delta | None":
        """Удалить узел по пути.

        Args:
            path: точечный путь к узлу.
            source: источник изменения.

        Returns:
            Delta если узел существовал, None если уже отсутствовал.
        """
        ...

    @abstractmethod
    def subscribe(self, pattern: str, callback: Callable) -> str:
        """Подписаться на изменения по glob-паттерну.

        Примечание: этот метод — на уровне TreeStore. В StateProxy используется
        SubscriptionManager через IPC (не напрямую TreeStore.subscribe).

        Args:
            pattern: glob-паттерн пути.
            callback: функция, вызываемая при изменении.

        Returns:
            subscription_id — строка-идентификатор подписки.
        """
        ...

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Отписаться по subscription_id.

        Args:
            subscription_id: идентификатор, полученный из subscribe().
        """
        ...


class IStateProxy(ABC):
    """Контракт StateProxy — клиентский прокси (живёт в каждом процессе).

    StateProxy наследует IStateProxy явно в задаче 2.1.3.
    GuiStateProxy наследует через цепочку StateProxy → IStateProxy.

    Каждый ProcessModule создаёт свой экземпляр StateProxy.
    Proxy общается с StateStoreManager через IPC (RouterManager).
    Кэширует подписанные пути для быстрого чтения.

    ADR-SS-009: ABC выбран для явного публичного контракта и mock-friendly тестов.
    """

    @abstractmethod
    def get(self, path: str, default: Any = None) -> Any:
        """Получить значение из локального кэша или через IPC fallback.

        Args:
            path: точечный путь к узлу.
            default: значение по умолчанию если путь не найден.

        Returns:
            Значение из кэша или через IPC.
        """
        ...

    @abstractmethod
    def set(self, path: str, value: Any) -> None:
        """Отправить state.set в StateStoreManager через IPC.

        Args:
            path: точечный путь к узлу.
            value: новое значение (pickle-совместимое).
        """
        ...

    @abstractmethod
    def merge(self, path: str, partial: dict) -> None:
        """Отправить state.merge в StateStoreManager через IPC.

        Args:
            path: путь к поддереву.
            partial: dict с ключами и значениями для слияния.
        """
        ...

    @abstractmethod
    def subscribe(
        self,
        pattern: str,
        callback: Callable,
        exclude_self: bool = False,
    ) -> str:
        """Подписаться на изменения по glob-паттерну.

        Отправляет state.subscribe в StateStoreManager через IPC.
        Регистрирует callback локально по sub_id.

        Args:
            pattern: glob-паттерн пути, например 'cameras.*.config.*'.
            callback: функция вызывается при получении дельт.
            exclude_self: если True — не получать собственные изменения.

        Returns:
            sub_id — строка-идентификатор подписки.
        """
        ...

    @abstractmethod
    def unsubscribe(self, sub_id: str) -> None:
        """Отписаться по sub_id.

        Args:
            sub_id: идентификатор, полученный из subscribe().
        """
        ...

    @abstractmethod
    def on_state_changed(self, message: dict) -> None:
        """Handler для входящего state.changed сообщения от сервера.

        Обновляет локальный кэш и вызывает зарегистрированные callbacks.
        Регистрируется через router.register_message_handler("state.changed", ...).

        Args:
            message: IPC-сообщение с полями command, deltas, targets.
        """
        ...


class IStateStoreManager(ABC):
    """Контракт StateStoreManager — серверный фасад (живёт в ProcessManagerProcess).

    StateStoreManager наследует IStateStoreManager явно в задаче 2.1.3.
    Содержит TreeStore + SubscriptionManager + DeltaDispatcher.
    Обрабатывает IPC-сообщения: state.set, state.merge, state.get,
    state.subscribe, state.unsubscribe, state.unsubscribe_all, state.get_subtree.

    ADR-SS-009: ABC для явного публичного API и тестируемости.
    """

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализировать хранилище. Регистрирует IPC-обработчики если router задан.

        Returns:
            True если инициализация успешна.
        """
        ...

    @abstractmethod
    def shutdown(self) -> bool:
        """Graceful остановка. Отписывает все подписки.

        Returns:
            True если остановка прошла успешно.
        """
        ...

    @abstractmethod
    def use(self, middleware: Any) -> None:
        """Подключить middleware в pipeline.

        Args:
            middleware: экземпляр StateMiddleware.
        """
        ...

    @abstractmethod
    def register_commands(self, command_manager: Any) -> None:
        """Зарегистрировать команды управления в CommandManager.

        Args:
            command_manager: экземпляр CommandManager из command_module.
        """
        ...

    @abstractmethod
    def register_message_handlers(self, router: IRouter) -> None:
        """Зарегистрировать IPC message-handlers в Router.

        Регистрирует handlers для 7 команд:
        state.set, state.merge, state.get, state.get_subtree,
        state.subscribe, state.unsubscribe, state.unsubscribe_all.

        Args:
            router: реализация IRouter (RouterManager или InMemoryRouter в тестах).
        """
        ...
