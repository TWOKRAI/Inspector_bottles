# -*- coding: utf-8 -*-
"""
ChannelRegistry — потокобезопасный реестр каналов (generic).

Обобщённая версия router_module/_channel_registry.py:
  - Работает с IChannel (базовый интерфейс), не привязан к IMessageChannel
  - Используется ChannelRoutingManager (и всеми наследниками)

Жизненный цикл:
    registry = ChannelRegistry()
    registry.register(FileChannel("logs"))
    registry.register(QueueChannel("ctrl", q))

    ch  = registry.get("logs")        # получить по имени
    all = registry.all()              # все каналы
    old = registry.clear()            # очистить (для shutdown cleanup)
"""

import threading
from typing import Any, Callable, Dict, List, Optional

from ..._fallback import emergency_log
from ..interfaces import IChannel

#: Имя аварийного вида. Реестр каналов не может рассказать о своей поломке
#: каналом — писать приходится в stdlib напрямую (см. `emergency_log`).
_EMERGENCY_NAME = __name__


class ChannelRegistry:
    """Потокобезопасный реестр каналов IChannel.

    Все мутирующие операции (register, unregister, clear) и все читающие
    операции (get, all, snapshot) защищены threading.RLock.

    Thread safety note:
        snapshot() выполняется под lock'ом. Последующие операции с каналами
        выполняются вне lock'а — медленный I/O не блокирует другие потоки.
    """

    def __init__(
        self,
        log_warning: Optional[Callable] = None,
        log_error: Optional[Callable] = None,
        log_debug: Optional[Callable] = None,
    ) -> None:
        self._channels: Dict[str, IChannel] = {}
        self._lock = threading.RLock()

        # D1: без переданных разъёмов реестр раньше молчал ПОЛНОСТЬЮ (`lambda: None`),
        # и «менеджеров нет» выглядело снаружи так же, как «всё в порядке». Молчание
        # заменено аварийным выходом: диагностика уходит в stdlib напрямую — реестр
        # каналов не может рассказать о своей поломке каналом. Debug остаётся немым:
        # это шум штатной работы, а не сигнал.
        self._log_warning = log_warning or (lambda msg: emergency_log(_EMERGENCY_NAME, "WARNING", "%s", msg))
        self._log_error = log_error or (lambda msg: emergency_log(_EMERGENCY_NAME, "ERROR", "%s", msg))
        self._log_debug = log_debug or (lambda msg: None)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, channel: IChannel) -> bool:
        """Зарегистрировать канал.

        Принимает любой объект, реализующий IChannel.
        Если канал с таким именем уже есть — заменяет с предупреждением.
        """
        if not isinstance(channel, IChannel):
            self._log_error(f"[ChannelRegistry] register: '{type(channel).__name__}' does not implement IChannel")
            return False
        with self._lock:
            replaced = channel.name in self._channels
            self._channels[channel.name] = channel
        # D1, AB/BA: разъём зовётся ПОСЛЕ отпускания лока. Прежде предупреждение
        # писалось изнутри `with self._lock`, то есть реестр держал свой лок и
        # брал лок логгера, а логгер по другому пути (раздача в tap → запись в
        # канал → чтение реестра) берёт их в обратном порядке. Цикла не было
        # только потому, что так сложилась проводка, — а это не гарантия, это
        # везение. Теперь порядок «лок реестра → лок логгера» невозможен
        # структурно: под локом реестра не зовётся ничего чужого.
        if replaced:
            self._log_warning(f"[ChannelRegistry] channel '{channel.name}' replaced")
        self._log_debug(f"[ChannelRegistry] channel '{channel.name}' registered (type={channel.channel_type})")
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

    def get(self, name: str) -> Optional[IChannel]:
        """Получить канал по имени или None."""
        with self._lock:
            return self._channels.get(name)

    def all(self) -> List[IChannel]:
        """Список всех каналов."""
        with self._lock:
            return list(self._channels.values())

    def names(self) -> List[str]:
        """Список имён всех каналов."""
        with self._lock:
            return list(self._channels.keys())

    def snapshot(self) -> Dict[str, IChannel]:
        """Копия словаря channel_name → channel (потокобезопасно)."""
        with self._lock:
            return dict(self._channels)

    def clear(self) -> List[IChannel]:
        """Очистить реестр. Возвращает список удалённых каналов (для close/stop_listening)."""
        with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        return channels

    # ------------------------------------------------------------------
    # Info / Stats
    # ------------------------------------------------------------------

    def get_info(self) -> Dict[str, Any]:
        """Информация о всех каналах (для статистики и диагностики)."""
        snap = self.snapshot()
        result: Dict[str, Any] = {}
        for name, ch in snap.items():
            try:
                result[name] = ch.get_info()
            except Exception:
                result[name] = {"name": name, "type": ch.channel_type}
        return result

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._channels)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._channels

    def __repr__(self) -> str:
        return f"ChannelRegistry(channels={self.names()})"
