# -*- coding: utf-8 -*-
"""
FanoutChannel — канал-мультиплексор для RouterManager.

Отправляет одно сообщение в несколько дочерних каналов одновременно.
Используется когда одно событие (например, изменение регистра) должно
параллельно попасть в несколько назначений:

    Пример:
        fanout = FanoutChannel(
            name="control_draw_fanout",
            channels=[
                QueueChannel("control_draw", queue_draw, event_draw),
                DatabaseChannel("db_draw", db_connection),   # будущий канал
            ]
        )
        router.register_channel(fanout)
        router.send(msg)  # → в оба канала одновременно

FanoutChannel реализует тот же интерфейс MessageChannel, поэтому
RouterManager не знает, что за ним стоит несколько каналов.
Добавление нового назначения — fanout.add_channel(new_ch) — без изменений
в остальном коде.
"""
from typing import Dict, Any, List

from ..channel import MessageChannel


class FanoutChannel(MessageChannel):
    """Канал-мультиплексор: маршрутизирует одно сообщение в N дочерних каналов.

    Особенности:
    - Дочерние каналы могут быть любого типа (QueueChannel, DatabaseChannel, …).
    - send() считается успешным, если хотя бы один дочерний канал принял сообщение.
    - poll() объединяет входящие сообщения из всех дочерних каналов.
    - Каналы можно добавлять и удалять динамически (add_channel / remove_channel).
    """

    def __init__(self, name: str, channels: List[MessageChannel] | None = None):
        """
        Args:
            name:     Уникальное имя канала для регистрации в RouterManager.
            channels: Список начальных дочерних каналов (опционально).
        """
        self._name = name
        self._channels: List[MessageChannel] = list(channels or [])

    # -------------------------------------------------------------------------
    # MessageChannel interface
    # -------------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "fanout"

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить сообщение во все дочерние каналы параллельно.

        Returns:
            Агрегированный результат: status="success" если хотя бы один
            дочерний канал принял сообщение.
        """
        results = []
        for ch in list(self._channels):
            try:
                result = ch.send(message)
            except Exception as exc:
                result = {"status": "error", "reason": str(exc), "channel": ch.name}
            results.append(result)

        sent_count = sum(1 for r in results if r.get("status") == "success")
        return {
            "status": "success" if sent_count > 0 else "error",
            "channel": self.name,
            "sent_to": sent_count,
            "total": len(results),
            "results": results,
        }

    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Собрать входящие сообщения из всех дочерних каналов."""
        messages: List[Dict[str, Any]] = []
        for ch in list(self._channels):
            try:
                messages.extend(ch.poll(timeout))
            except Exception:
                pass
        return messages

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["child_channels"] = [ch.name for ch in self._channels]
        info["child_count"] = len(self._channels)
        return info

    # -------------------------------------------------------------------------
    # Dynamic channel management
    # -------------------------------------------------------------------------

    def add_channel(self, channel: MessageChannel) -> None:
        """Добавить дочерний канал.

        Позволяет подключить новое назначение (например, DB-канал) без изменения
        кода, регистрирующего FanoutChannel в RouterManager.
        """
        if channel not in self._channels:
            self._channels.append(channel)

    def remove_channel(self, name: str) -> bool:
        """Удалить дочерний канал по имени.

        Returns:
            True если канал был найден и удалён.
        """
        before = len(self._channels)
        self._channels = [ch for ch in self._channels if ch.name != name]
        return len(self._channels) < before

    def get_channels(self) -> List[MessageChannel]:
        """Список текущих дочерних каналов (копия)."""
        return list(self._channels)

    def __repr__(self) -> str:
        names = [ch.name for ch in self._channels]
        return f"FanoutChannel(name={self._name!r}, channels={names})"
