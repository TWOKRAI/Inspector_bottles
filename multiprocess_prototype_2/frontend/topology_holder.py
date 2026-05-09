"""TopologyHolder — контейнер topology dict с уведомлениями об изменении.

Используется GUI-слоем для доступа к текущей topology без привязки к IPC.
Recipe Apply заменяет topology через set_topology() → слушатели обновляют UI.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class TopologyHolder:
    """Держатель текущей topology с уведомлениями об изменении.

    Хранит dict (deep copy при set), уведомляет подписчиков при замене.
    Thread-safety: НЕ потокобезопасен — вызывать только из Qt main thread.
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._topology: dict[str, Any] = initial or {}
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []

    @property
    def topology(self) -> dict[str, Any]:
        """Текущая topology (ссылка, не копия — для производительности)."""
        return self._topology

    def set_topology(self, new_topology: dict[str, Any]) -> dict[str, Any]:
        """Заменить topology. Возвращает предыдущую (deep copy).

        Args:
            new_topology: новая topology dict.

        Returns:
            Deep copy предыдущей topology (для undo).
        """
        previous = copy.deepcopy(self._topology)
        self._topology = new_topology
        self._notify(new_topology)
        return previous

    def on_changed(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Подписаться на изменения topology.

        Callback получает новую topology dict при каждом set_topology().
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Отписаться от изменений."""
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def _notify(self, topology: dict[str, Any]) -> None:
        """Уведомить всех подписчиков."""
        for cb in self._callbacks:
            try:
                cb(topology)
            except Exception:
                logger.exception("Ошибка в topology change callback %r", cb)
