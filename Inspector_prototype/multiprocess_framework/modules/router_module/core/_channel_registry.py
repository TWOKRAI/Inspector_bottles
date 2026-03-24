# -*- coding: utf-8 -*-
"""
ChannelRegistry — потокобезопасный реестр каналов.

Изолирует управление каналами (регистрация / удаление / опрос) от RouterManager.
Все операции защищены RLock — реестр можно использовать из любого потока.

Жизненный цикл:
    registry = ChannelRegistry()
    registry.register(QueueChannel("ctrl", q))
    registry.register(QueueChannel("log", log_q))

    msgs = registry.poll_all()        # опросить все каналы
    ch   = registry.get("ctrl")       # получить по имени
    channels = registry.clear()       # очистить (возвращает список для stop_listening)
"""
import threading
from typing import Any, Callable, Dict, List, Optional

from ..interfaces import IMessageChannel


class ChannelRegistry:
    """Потокобезопасный реестр каналов сообщений.

    Хранит каналы по имени. Все мутирующие операции (register, unregister, clear)
    и все читающие операции (get, all, snapshot) защищены threading.RLock.

    poll_all() снимает snapshot под lock'ом, затем опрашивает вне lock'а —
    медленная блокировка на poll не мешает другим потокам модифицировать реестр.
    """

    def __init__(
        self,
        log_warning: Optional[Callable] = None,
        log_error:   Optional[Callable] = None,
        log_debug:   Optional[Callable] = None,
    ) -> None:
        self._channels: Dict[str, IMessageChannel] = {}
        self._lock = threading.RLock()

        self._log_warning = log_warning or (lambda msg: None)
        self._log_error   = log_error   or (lambda msg: None)
        self._log_debug   = log_debug   or (lambda msg: None)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, channel: IMessageChannel) -> bool:
        """Зарегистрировать канал.

        Принимает любой объект, реализующий IMessageChannel (не обязательно MessageChannel).
        Если канал с таким именем уже есть — заменяет с предупреждением.
        """
        if not isinstance(channel, IMessageChannel):
            self._log_error(
                f"[ChannelRegistry] register: '{type(channel).__name__}' "
                f"does not implement IMessageChannel"
            )
            return False
        with self._lock:
            if channel.name in self._channels:
                self._log_warning(f"[ChannelRegistry] channel '{channel.name}' replaced")
            self._channels[channel.name] = channel
        self._log_debug(f"[ChannelRegistry] channel '{channel.name}' registered ({channel.channel_type})")
        return True

    def unregister(self, name: str) -> bool:
        """Удалить канал по имени. Возвращает False если канал не найден."""
        with self._lock:
            if name not in self._channels:
                return False
            del self._channels[name]
        self._log_debug(f"[ChannelRegistry] channel '{name}' unregistered")
        return True

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[IMessageChannel]:
        """Получить канал по имени или None."""
        with self._lock:
            return self._channels.get(name)

    def all(self) -> List[IMessageChannel]:
        """Список всех каналов."""
        with self._lock:
            return list(self._channels.values())

    def names(self) -> List[str]:
        """Список имён всех каналов."""
        with self._lock:
            return list(self._channels.keys())

    def snapshot(self) -> Dict[str, IMessageChannel]:
        """Копия словаря channel_name → channel."""
        with self._lock:
            return dict(self._channels)

    def clear(self) -> List[IMessageChannel]:
        """Очистить реестр. Возвращает список удалённых каналов (для stop_listening)."""
        with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        return channels

    def __len__(self) -> int:
        with self._lock:
            return len(self._channels)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._channels

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def poll_all(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Опросить все каналы и вернуть список сообщений.

        Алгоритм:
          1. Снять snapshot каналов под lock'ом (мгновенно).
          2. Опрашивать каждый канал вне lock'а (может быть медленным для сокетов).

        Каждое сообщение получает поле '_source_channel' с именем канала.
        """
        snapshot = self.snapshot()
        messages: List[Dict[str, Any]] = []

        for ch_name, ch in snapshot.items():
            try:
                batch = ch.poll(timeout)
                for msg in batch:
                    if isinstance(msg, dict):
                        msg["_source_channel"] = ch_name
                messages.extend(batch)
            except Exception as e:
                self._log_error(f"[ChannelRegistry] poll error on '{ch_name}': {e}")

        return messages

    def get_info(self) -> Dict[str, Any]:
        """Информация о всех каналах для статистики."""
        snapshot = self.snapshot()
        result: Dict[str, Any] = {}
        for name, ch in snapshot.items():
            try:
                result[name] = ch.get_info()
            except Exception:
                result[name] = {"name": name, "type": ch.channel_type}
        return result
