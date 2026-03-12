# -*- coding: utf-8 -*-
"""
MessageChannel — абстрактный базовый класс для всех каналов сообщений.

Добавляет к IMessageChannel:
  - Инъекцию log-колбэков (log_warning, log_error) через конструктор
    или через _attach_logger() вызываемый RouterManager при регистрации.
  - self._log_warning / self._log_error — всегда callable, не None.

Создание канала без логгера — корректно (молчаливый no-op):
    ch = QueueChannel("ctrl", q)                   # без логгера

Создание с явными колбэками:
    ch = QueueChannel("ctrl", q, log_error=my_fn)

RouterManager инжектит свои колбэки автоматически при register_channel():
    router.register_channel(ch)   # → ch._attach_logger(router._log_warning, ...)
"""
from abc import abstractmethod
from typing import Callable, Dict, Any, List, Optional

from ..interfaces import IMessageChannel


class MessageChannel(IMessageChannel):
    """Абстрактный базовый класс канала с поддержкой инъекции логирования.

    Все конкретные каналы (QueueChannel, SocketChannel, ...) наследуют этот класс
    и получают готовые self._log_warning / self._log_error без дублирования кода.
    """

    def __init__(
        self,
        log_warning: Optional[Callable[[str], None]] = None,
        log_error:   Optional[Callable[[str], None]] = None,
    ) -> None:
        self._log_warning = log_warning or (lambda msg: None)
        self._log_error   = log_error   or (lambda msg: None)

    def _attach_logger(
        self,
        log_warning: Callable[[str], None],
        log_error:   Callable[[str], None],
    ) -> None:
        """Подключить логирование от RouterManager после регистрации.

        Вызывается автоматически RouterManager.register_channel().
        Переопределять не нужно.
        """
        self._log_warning = log_warning
        self._log_error   = log_error

    # ---- Обязательные (реализуются в подклассах) ----

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя канала."""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Тип: 'queue', 'socket', 'http', 'db', 'log', ..."""

    @abstractmethod
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить сообщение. Вернуть {"status": "success"|"error", ...}."""

    @abstractmethod
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Опросить канал. timeout=0 → non-blocking."""
