"""in_memory_router.py — InMemoryRouter для unit-тестов прикладного кода.

Реализует IRouter Protocol без реальных IPC-каналов.
Сообщения доставляются синхронно в том же процессе.

Использование:
    from multiprocess_framework.modules.state_store_module.testing import InMemoryRouter
    from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
    from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

    router = InMemoryRouter()
    manager = StateStoreManager(router=router, initial_state={})
    manager.initialize()

    proxy = StateProxy("test_proc", router=router)
    router.register_message_handler("state.changed", proxy.on_state_changed)

    proxy.set("some.path", 42)
    assert proxy.get("some.path") == 42
"""
from typing import Callable


class InMemoryRouter:
    """Mock-реализация IRouter для тестирования.

    Хранит зарегистрированные handlers и доставляет сообщения синхронно.
    Совместим с IRouter Protocol (ADR-SS-001, ADR-SS-010).

    Отличие от MockBus в integration-тестах:
        InMemoryRouter — публичный API модуля для прикладных тестов.
        Поддерживает один handler на ключ (register_message_handler перезаписывает).
        MockBus (в тестах прототипа) поддерживает несколько handlers на ключ
        и таргетную доставку state.changed — специфика интеграционного теста.
    """

    def __init__(self) -> None:
        # ключ команды → один handler
        self._handlers: dict[str, Callable] = {}
        # лог всех отправленных сообщений (для assertions в тестах)
        self.sent_messages: list[dict] = []

    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
    ) -> None:
        """Зарегистрировать handler на IPC-команду.

        Повторная регистрация на тот же key перезаписывает предыдущий handler.

        Args:
            key: имя IPC-команды, например 'state.set'.
            handler: callable, принимающий dict-сообщение.
            expects_full_message: игнорируется (все handlers получают полное сообщение).
        """
        self._handlers[key] = handler

    def send_async(self, message: dict, priority: str = "normal") -> None:
        """Синхронная доставка сообщения (в тестах async не нужен).

        Ключ команды берётся из message["type"] или message["command"].
        Если handler зарегистрирован — вызывается синхронно.

        Args:
            message: IPC-сообщение (dict).
            priority: игнорируется (без очереди приоритетов в тестах).
        """
        self.sent_messages.append(message)
        key = message.get("type") or message.get("command")
        if key and key in self._handlers:
            self._handlers[key](message)

    def send(self, message: dict) -> dict | None:
        """Синхронная отправка с возвратом ответа от handler-а.

        Используется StateProxy для state.subscribe, state.get и state.get_subtree
        (ожидают ответ от сервера).

        Args:
            message: IPC-сообщение (dict).

        Returns:
            Ответ handler-а (dict) или None если handler не зарегистрирован.
        """
        self.sent_messages.append(message)
        key = message.get("type") or message.get("command")
        if key and key in self._handlers:
            return self._handlers[key](message)
        return None

    def clear(self) -> None:
        """Сбросить историю сообщений между тестами.

        Не удаляет зарегистрированные handlers.
        """
        self.sent_messages.clear()
