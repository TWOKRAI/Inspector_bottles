"""state_store_manager.py — Серверная часть StateStore.

StateStoreManager живёт в ProcessManagerProcess и обрабатывает
IPC-сообщения от процессов: state.set, state.get, state.subscribe и т.д.

НЕ наследует ProcessModule — это компонент, встраиваемый в ProcessManagerProcess.
"""

from __future__ import annotations

from typing import Any

from ...base_manager import BaseManager, ObservableMixin

from ..core.subscription_manager import SubscriptionManager
from ..core.tree_store import TreeStore
from ..interfaces import IRouter, IStateStoreManager
from ..middleware.base import MiddlewarePipeline, StateMiddleware
from .delta_dispatcher import DeltaDispatcher


class StateStoreManager(BaseManager, ObservableMixin, IStateStoreManager):
    """Серверная часть StateStore. Живёт в ProcessManagerProcess.

    Содержит TreeStore + SubscriptionManager + DeltaDispatcher.
    Обрабатывает IPC-сообщения от процессов:
    - state.set -> TreeStore.set() -> dispatch deltas
    - state.merge -> TreeStore.merge() -> dispatch deltas
    - state.get -> TreeStore.get() -> response
    - state.subscribe -> SubscriptionManager.subscribe()
    - state.unsubscribe -> SubscriptionManager.unsubscribe()
    """

    def __init__(
        self,
        router: IRouter | None = None,
        initial_state: dict[str, Any] | None = None,
        manager_name: str = "StateStoreManager",
        logger: Any = None,
        stats: Any = None,
    ) -> None:
        """
        Args:
            router: реализация IRouter для IPC (None допустимо для тестов).
            initial_state: начальное состояние дерева.
            manager_name: имя менеджера для BaseManager.
            logger: LoggerManager или ObservableMixin-совместимый объект.
            stats: StatsManager или ObservableMixin-совместимый объект.
        """
        BaseManager.__init__(self, manager_name=manager_name)
        ObservableMixin.__init__(self, managers={"logger": logger, "stats": stats})
        self._store = TreeStore(initial=initial_state)
        self._subs = SubscriptionManager()
        self._dispatcher = DeltaDispatcher(
            subscription_mgr=self._subs,
            router=router,
            sender_name="StateStore",
            logger=self,
        )
        self._pipeline = MiddlewarePipeline()
        self._router = router

    @property
    def pipeline(self) -> MiddlewarePipeline:
        """Доступ к middleware pipeline (для тестов и конфигурации)."""
        return self._pipeline

    def use(self, middleware: StateMiddleware) -> None:
        """Добавить middleware в pipeline.

        Args:
            middleware: экземпляр StateMiddleware.
        """
        self._pipeline.use(middleware)

    @property
    def store(self) -> TreeStore:
        """Доступ к внутреннему TreeStore (для тестов и bootstrap)."""
        return self._store

    @property
    def subscription_manager(self) -> SubscriptionManager:
        """Доступ к SubscriptionManager (для тестов)."""
        return self._subs

    @property
    def dispatcher(self) -> DeltaDispatcher:
        """Доступ к DeltaDispatcher (для тестов)."""
        return self._dispatcher

    def initialize(self) -> bool:
        """Инициализация. Регистрирует IPC-обработчики если router задан.

        Returns:
            True если инициализация успешна.
        """
        if self._router is not None:
            self.register_message_handlers(self._router)

        self.is_initialized = True
        self._log_info("StateStoreManager инициализирован")
        return True

    def shutdown(self) -> bool:
        """Остановка. Отписывает все подписки.

        Returns:
            True если остановка успешна.
        """
        with self._subs._lock:
            subscribers = list(self._subs._by_subscriber.keys())

        total = 0
        for subscriber in subscribers:
            count = self._subs.unsubscribe_all(subscriber)
            total += count

        self.is_initialized = False
        self._log_info(f"StateStoreManager остановлен, отписано подписок: {total}")
        return True

    # -------------------------------------------------------------------
    # Извлечение данных из IPC-сообщения
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_data(msg: dict) -> dict:
        """Извлечь данные из IPC-сообщения.

        Совместимость с CommandManager (data-поле) и прямыми dict-сообщениями.
        Если в msg есть ключ 'data' и это dict — берём оттуда.
        Иначе — сам msg является данными.

        Args:
            msg: входящее IPC-сообщение.

        Returns:
            dict с данными запроса.
        """
        data = msg.get("data")
        if isinstance(data, dict):
            return data
        return msg

    # -------------------------------------------------------------------
    # IPC-обработчики
    # -------------------------------------------------------------------

    def handle_state_set(self, msg: dict) -> dict | None:
        """Обработчик state.set: установить значение по пути.

        msg.data: {path: str, value: Any, source: str}

        Returns:
            dict с результатом операции или ошибкой.
        """
        data = self._extract_data(msg)
        path = data.get("path")
        value = data.get("value")
        source = data.get("source", "")

        # Валидация обязательных полей
        if not path or not isinstance(path, str):
            return {"status": "error", "error": "Поле 'path' обязательно и должно быть строкой"}

        try:
            # --- MIDDLEWARE BEFORE ---
            proceed, value, context = self._pipeline.run_before_set(path, value, source)
            if not proceed:
                return {
                    "status": "rejected",
                    "path": path,
                    "reason": context.get("rejection_reason", "middleware"),
                }

            delta = self._store.set(path, value, source=source)
            if delta is not None:
                # --- MIDDLEWARE AFTER ---
                self._pipeline.run_after_set(delta, context)
                # Рассылка дельт подписчикам
                self._dispatcher.dispatch_single(delta)
                return {"status": "ok", "path": path, "changed": True}
            return {"status": "ok", "path": path, "changed": False}
        except (ValueError, TypeError) as exc:
            self._log_warning(f"state.set ошибка: {exc}")
            return {"status": "error", "error": str(exc)}

    def handle_state_merge(self, msg: dict) -> dict | None:
        """Обработчик state.merge: глубокий merge dict в поддерево.

        msg.data: {path: str, data: dict, source: str}

        Returns:
            dict с результатом операции или ошибкой.
        """
        data = self._extract_data(msg)
        path = data.get("path", "")
        merge_data = data.get("data")
        source = data.get("source", "")

        if merge_data is None or not isinstance(merge_data, dict):
            return {"status": "error", "error": "Поле 'data' обязательно и должно быть dict"}

        try:
            # --- MIDDLEWARE BEFORE ---
            proceed, merge_data, context = self._pipeline.run_before_merge(path, merge_data, source)
            if not proceed:
                return {
                    "status": "rejected",
                    "path": path,
                    "reason": context.get("rejection_reason", "middleware"),
                }

            deltas = self._store.merge(path, merge_data, source=source)
            if deltas:
                # --- MIDDLEWARE AFTER ---
                self._pipeline.run_after_merge(deltas, context)
                self._dispatcher.dispatch(deltas)
            return {
                "status": "ok",
                "path": path,
                "changes_count": len(deltas),
            }
        except (ValueError, TypeError) as exc:
            self._log_warning(f"state.merge ошибка: {exc}")
            return {"status": "error", "error": str(exc)}

    def handle_state_get(self, msg: dict) -> dict:
        """Обработчик state.get: прочитать значение по пути.

        msg.data: {path: str, request_id: str}

        Returns:
            dict с value и request_id, или ошибкой.
        """
        data = self._extract_data(msg)
        path = data.get("path", "")
        request_id = data.get("request_id", "")

        try:
            value = self._store.get(path)
            return {
                "status": "ok",
                "request_id": request_id,
                "value": value,
            }
        except KeyError:
            return {
                "status": "error",
                "request_id": request_id,
                "error": f"Путь не существует: '{path}'",
            }

    def handle_state_get_subtree(self, msg: dict) -> dict:
        """Обработчик state.get_subtree: прочитать поддерево по пути.

        msg.data: {path: str, request_id: str}

        Returns:
            dict с value (поддерево) и request_id, или ошибкой.
        """
        data = self._extract_data(msg)
        path = data.get("path", "")
        request_id = data.get("request_id", "")

        try:
            value = self._store.get_subtree(path)
            return {
                "status": "ok",
                "request_id": request_id,
                "value": value,
            }
        except (KeyError, TypeError) as exc:
            return {
                "status": "error",
                "request_id": request_id,
                "error": str(exc),
            }

    def handle_state_subscribe(self, msg: dict) -> dict:
        """Обработчик state.subscribe: подписаться на изменения.

        msg.data: {pattern: str, subscriber: str, exclude_sources?: list[str]}

        Returns:
            dict с sub_id или ошибкой.
        """
        data = self._extract_data(msg)
        pattern = data.get("pattern")
        subscriber = data.get("subscriber")
        exclude_sources = data.get("exclude_sources", ())

        if not pattern or not isinstance(pattern, str):
            return {"status": "error", "error": "Поле 'pattern' обязательно"}
        if not subscriber or not isinstance(subscriber, str):
            return {"status": "error", "error": "Поле 'subscriber' обязательно"}

        # Приводим exclude_sources к tuple
        if isinstance(exclude_sources, list):
            exclude_sources = tuple(exclude_sources)

        sub_id = self._subs.subscribe(
            pattern=pattern,
            subscriber=subscriber,
            exclude_sources=exclude_sources,
        )
        self._log_debug(f"Подписка создана: sub_id={sub_id}, subscriber={subscriber}, pattern={pattern}")
        return {"status": "ok", "sub_id": sub_id}

    def handle_state_unsubscribe(self, msg: dict) -> dict:
        """Обработчик state.unsubscribe: отписаться от подписки.

        msg.data: {sub_id: str}

        Returns:
            dict с success.
        """
        data = self._extract_data(msg)
        sub_id = data.get("sub_id")

        if not sub_id:
            return {"status": "error", "error": "Поле 'sub_id' обязательно"}

        success = self._subs.unsubscribe(sub_id)
        return {"status": "ok", "success": success}

    def handle_state_unsubscribe_all(self, msg: dict) -> dict:
        """Обработчик state.unsubscribe_all: отписать все подписки процесса.

        msg.data: {subscriber: str}

        Returns:
            dict с count удалённых подписок.
        """
        data = self._extract_data(msg)
        subscriber = data.get("subscriber")

        if not subscriber:
            return {"status": "error", "error": "Поле 'subscriber' обязательно"}

        count = self._subs.unsubscribe_all(subscriber)
        return {"status": "ok", "count": count}

    # -------------------------------------------------------------------
    # Регистрация в CommandManager и RouterManager
    # -------------------------------------------------------------------

    def register_commands(self, command_manager: Any) -> None:
        """Регистрирует все обработчики в CommandManager ProcessManager'а.

        Вызывается из ProcessManagerProcess при инициализации.

        Args:
            command_manager: экземпляр CommandManager.
        """
        commands = {
            "state.set": (self.handle_state_set, "Установить значение в дереве"),
            "state.merge": (self.handle_state_merge, "Глубокий merge dict в поддерево"),
            "state.get": (self.handle_state_get, "Прочитать значение из дерева"),
            "state.get_subtree": (self.handle_state_get_subtree, "Прочитать поддерево"),
            "state.subscribe": (self.handle_state_subscribe, "Подписаться на изменения"),
            "state.unsubscribe": (self.handle_state_unsubscribe, "Отписаться от подписки"),
            "state.unsubscribe_all": (
                self.handle_state_unsubscribe_all,
                "Отписать все подписки процесса",
            ),
        }

        for name, (handler, description) in commands.items():
            command_manager.register_command(
                name,
                handler,
                metadata={"description": description},
                tags=["state_store"],
            )

        self._log_info(f"StateStoreManager: зарегистрировано {len(commands)} команд в CommandManager")

    def register_message_handlers(self, router: IRouter) -> None:
        """Регистрирует message handlers в Router.

        Args:
            router: реализация IRouter (RouterManager или InMemoryRouter в тестах).
        """
        handlers = {
            "state.set": self.handle_state_set,
            "state.merge": self.handle_state_merge,
            "state.get": self.handle_state_get,
            "state.get_subtree": self.handle_state_get_subtree,
            "state.subscribe": self.handle_state_subscribe,
            "state.unsubscribe": self.handle_state_unsubscribe,
            "state.unsubscribe_all": self.handle_state_unsubscribe_all,
        }

        for key, handler in handlers.items():
            router.register_message_handler(key, handler, expects_full_message=True)

        self._log_info(f"StateStoreManager: зарегистрировано {len(handlers)} обработчиков в Router")
