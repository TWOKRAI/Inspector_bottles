# -*- coding: utf-8 -*-
"""
Публичные контракты channel_routing_module.

IChannel                — базовый контракт любого канала вывода данных
IBufferStrategy         — стратегия буферизации (enqueue / flush / start / stop)
IChannelRoutingManager  — базовый контракт менеджера маршрутизации по каналам
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..base_manager.interfaces import IBaseManager


# =============================================================================
# IChannel
# =============================================================================


class IChannel(ABC):
    """Базовый контракт любого канала вывода данных.

    Наследники:
        IMessageChannel (router_module)  — добавляет poll(), send(), start_listening()
        ILogChannel     (logger_module)  — уже совместим (name + write + close + get_info)

    Все существующие каналы (QueueChannel, FileChannel, ConsoleChannel) должны
    либо напрямую наследовать IChannel, либо предоставлять тот же интерфейс.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя канала."""

    @property
    def channel_type(self) -> str:
        """Тип канала (queue, file, console, http, …)."""
        return "generic"

    @abstractmethod
    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Записать данные в канал.

        Args:
            data: Словарь с данными (format зависит от типа канала)

        Returns:
            {"status": "success"|"error", "channel": name, ...}
        """

    def close(self) -> None:
        """Закрыть канал и освободить ресурсы."""

    def get_info(self) -> Dict[str, Any]:
        """Информация о канале (для статистики / диагностики)."""
        return {"name": self.name, "type": self.channel_type, "active": True}


def channel_accepted(result: Any) -> bool:
    """Принял ли канал запись — единственное толкование ответа :meth:`IChannel.write`.

    Живёт рядом с контрактом, который толкует, и намеренно НЕ в
    ``logger_module``: разбирать ответ канала обязан каждый, кто в канал
    пишет. Пока предикат жил приватным в логгере, severity-путь
    ``ErrorManager`` его просто не звал — писал ``ch.write(...)`` и уходил.
    Ценой была не стилистика: закрытый или отброшенный приёмник считался
    записавшим, floor (Ф0.9) не срабатывал, ``errors_to_floor`` оставался
    нулём — ошибка исчезала, и «маршрут сломан» не было видно ни по файлу,
    ни по счётчику. Найдено ревью Ф0.9 с воспроизведением.

    ``write`` ловит свои ошибки САМ и наружу не бросает, поэтому «не бросил»
    не равно «записал»: судить можно только по статусу.

    Каналы, не возвращающие статус (``None`` / не-``dict``), считаются
    принявшими — прежний контракт, ломать его на ровном месте нельзя.
    """
    if isinstance(result, dict):
        return result.get("status") != "error"
    return True


# =============================================================================
# IBufferStrategy
# =============================================================================


class IBufferStrategy(ABC):
    """Стратегия буферизации для ChannelRoutingManager.

    Реализации:
        AsyncSenderBuffer — PriorityQueue + фоновый поток (для RouterManager)
        BatchBuffer       — deque + lock + timer (для LoggerManager)
        DirectBuffer      — без буферизации, прямой вызов write() (для тестов)

    Контракт send_fn:
        Буфер получает send_fn(channel_name: str, data: Dict) → Any при создании.
        Эта функция выполняет фактическую запись в канал.
    """

    @abstractmethod
    def enqueue(self, channel: str, data: Dict[str, Any], priority: str = "normal") -> None:
        """Поместить данные в буфер для последующей отправки в канал.

        Args:
            channel:  Имя канала-получателя
            data:     Данные для отправки
            priority: Приоритет ("urgent" | "high" | "normal" | "low")
        """

    @abstractmethod
    def flush(self, channel: Optional[str] = None) -> None:
        """Принудительно сбросить буфер.

        Args:
            channel: Имя конкретного канала или None (сбросить все каналы)
        """

    @abstractmethod
    def start(self) -> None:
        """Запустить фоновые ресурсы (потоки, таймеры)."""

    @abstractmethod
    def stop(self) -> None:
        """Остановить фоновые ресурсы (корректное завершение)."""

    @property
    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """Статистика буфера (queued, dropped, flushed и т.д.)."""


# =============================================================================
# IChannelRoutingManager
# =============================================================================


class IChannelRoutingManager(IBaseManager):
    """Контракт базового менеджера маршрутизации по каналам.

    Предоставляет единый API управления каналами — независимо от того,
    это RouterManager, LoggerManager или StatsManager.
    """

    # ---- Управление каналами ----

    @abstractmethod
    def register_channel(self, channel: IChannel) -> bool:
        """Зарегистрировать канал. Возвращает False если канал невалидный."""

    @abstractmethod
    def unregister_channel(self, name: str) -> bool:
        """Удалить канал по имени. Возвращает False если не найден."""

    @abstractmethod
    def get_channel(self, name: str) -> Optional[IChannel]:
        """Получить канал по имени или None."""

    @abstractmethod
    def get_all_channels(self) -> List[IChannel]:
        """Список всех зарегистрированных каналов."""

    # ---- Маршрутизация ----
    #
    # ``route(data, key_field)`` был здесь и снят в Ф4.6 вместе с реализацией.
    # Контракт обещал единый key-based путь доставки для всех наследников, а на
    # деле каждый из четырёх маршрутизировал своим путём и метод не звал никто,
    # кроме тестов базы. Абстрактный метод, который все наследуют и никто не
    # использует, — это не контракт, а приглашение построить второй механизм.

    # ---- Буферизация ----

    @abstractmethod
    def flush(self) -> None:
        """Принудительно сбросить буфер (если используется)."""

    # ---- Реконфигурация (hot-reload) ----

    @abstractmethod
    def reconfigure(self, config: Dict[str, Any]) -> bool:
        """Пересобрать каналы/маршруты из нового конфига (full-rebuild).

        Закрывает текущий набор каналов и строит новый из переданного dict.
        Базовая реализация в ChannelRoutingManager оркеструет общую часть
        (flush → close → normalize → rebuild-hook); наследники переопределяют
        внутренний хук ``_rebuild_from_config`` под свой формат конфига.

        Args:
            config: dict (или объект с build()) с новой конфигурацией.

        Returns:
            True при успешной пересборке; False при невалидном config или ошибке
            (процесс не роняется — ошибка логируется).
        """


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "IChannel",
    "channel_accepted",
    "IBufferStrategy",
    "IChannelRoutingManager",
]
