# -*- coding: utf-8 -*-
"""
RouterAdapter — адаптер RouterManager для использования внутри ProcessModule.

Роль в архитектуре:
    ProcessModule.router_manager  →  RouterAdapter  →  RouterManager

Адаптер предоставляет:
  - Тонкую обёртку над RouterManager с контекстом процесса (sender name).
  - Методы send / receive / register_channel / start_listening делегируют в менеджер.
  - send_to_channel(channel_name, msg) — автоматически добавляет поле "sender".
  - Агрегированную статистику (адаптер + менеджер).

Что НЕ делает адаптер:
  - Не знает о process_name → channel_name mapping (это зона ProcessCommunication).
  - Не дублирует send_to_process / broadcast (эта логика в ProcessCommunication).
"""
from typing import Any, Callable, Dict, List, Optional, Union

from ...base_manager.adapters.base_adapter import BaseAdapter
from ..interfaces import IMessageChannel

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...message_module import Message


class RouterAdapter(BaseAdapter):
    """Адаптер для интеграции RouterManager в ProcessModule.

    Создаётся ProcessManagers при инициализации процесса:
        adapter = RouterAdapter(router_manager, process=self)

    После этого доступен через process.router_adapter.
    """

    def __init__(self, router_manager, process: Optional[Any] = None) -> None:
        super().__init__(router_manager, process, "RouterAdapter")

    # ---- BaseAdapter lifecycle ----

    def setup(self) -> bool:
        """Проверить что менеджер присутствует и пометить адаптер инициализированным."""
        if not self.manager:
            self._log("error", "RouterManager not set")
            return False
        self._initialized = True
        self._log("info", "RouterAdapter initialized")
        return True

    # ---- Отправка ----

    def send(self, message: Union["Message", Dict[str, Any]]) -> Dict[str, Any]:
        """Синхронная отправка через RouterManager.
        Для UI-потоков используй send_async().
        """
        if not self.manager:
            return {"status": "error", "reason": "RouterManager not available"}
        return self.manager.send(message)

    def send_async(
        self,
        message: Union["Message", Dict[str, Any]],
        priority: str = "normal",
    ) -> None:
        """Non-blocking отправка. Безопасна для UI-потока.
        priority: "urgent" | "high" | "normal" | "low"
        """
        if self.manager:
            self.manager.send_async(message, priority=priority)

    def send_to_channel(
        self,
        channel_name: str,
        message: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Отправить сообщение в именованный канал, добавив поле 'sender'.

        Удобный shorthand:
            adapter.send_to_channel("process_2_worker_in", {"command": "ping", ...})
        вместо:
            router.send({"channel": "process_2_worker_in", "sender": self.name, ...})
        """
        if not self.manager:
            return {"status": "error", "reason": "RouterManager not available"}
        msg = dict(message)
        msg["channel"] = channel_name
        if "sender" not in msg and self.process:
            msg["sender"] = getattr(self.process, "name", "unknown")
        return self.manager.send(msg)

    # ---- Получение ----

    def receive(
        self,
        timeout: float = 0.0,
        return_messages: bool = True,
    ) -> List[Any]:
        """Синхронный опрос всех зарегистрированных каналов."""
        if not self.manager:
            return []
        return self.manager.receive(timeout=timeout, return_messages=return_messages)

    def start_listening(self, poll_interval: float = 0.01) -> bool:
        """Запустить фоновый поток-приёмник.
        Все входящие сообщения будут переданы зарегистрированным callbacks.
        """
        if not self.manager:
            return False
        return self.manager.start_listening(poll_interval=poll_interval)

    def stop_listening(self) -> bool:
        """Остановить поток-приёмник."""
        if not self.manager:
            return False
        return self.manager.stop_listening()

    def add_callback(self, callback: Callable) -> None:
        """Зарегистрировать callback(msg) для входящих сообщений (async receive)."""
        if self.manager:
            self.manager.add_message_callback(callback)

    def remove_callback(self, callback: Callable) -> None:
        """Удалить callback."""
        if self.manager:
            self.manager.remove_message_callback(callback)

    # ---- Каналы ----

    def register_channel(self, channel: IMessageChannel) -> bool:
        """Зарегистрировать канал в RouterManager."""
        if not self.manager:
            return False
        return self.manager.register_channel(channel)

    # ---- Обработчики входящих ----

    def add_message_handler(self, key: str, handler: Callable) -> bool:
        """Зарегистрировать обработчик входящего сообщения по ключу command/type."""
        if not self.manager:
            return False
        return self.manager.register_message_handler(key, handler)

    # ---- Статистика ----

    def get_stats(self) -> Dict[str, Any]:
        """Статистика адаптера + менеджера."""
        stats = super().get_stats()
        if self.manager and hasattr(self.manager, "get_stats"):
            try:
                stats["manager"] = self.manager.get_stats()
            except Exception:
                pass
        return stats
