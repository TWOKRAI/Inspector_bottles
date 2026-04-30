"""ProcessMonitorModel — хранилище состояний процессов для вкладки «Процессы».

Простая модель без dirty tracking (в отличие от BaseEditorModel).
Хранит снимок статусов всех известных процессов и оповещает подписчиков
при любом изменении.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class ProcessMonitorModel:
    """Модель данных мониторинга процессов.

    Хранит dict[str, dict] — отображение имя_процесса → данные статуса.
    Формат данных одного процесса (совместим с get_all_status()):
        {
            "alive":    bool,
            "pid":      int | None,
            "exitcode": int | None,
            "name":     str,
            "status":   str,   # "running" | "stopped" | "crashed" | ...
            ...прочие ключи из broadcast...
        }
    """

    def __init__(self) -> None:
        # Основное хранилище: имя_процесса → dict с данными
        self._processes: dict[str, dict] = {}
        # Список callbacks для оповещения об изменениях
        self._callbacks: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Управление данными
    # ------------------------------------------------------------------

    def update_process(self, name: str, data: dict) -> None:
        """Обновить данные одного процесса.

        Args:
            name: Имя процесса (ключ).
            data: Словарь с новыми данными (будет смёрджен с существующими).
        """
        existing = self._processes.get(name, {})
        merged = {**existing, **data}
        self._processes[name] = merged
        logger.debug("ProcessMonitorModel: обновлён процесс %r -> %r", name, merged)
        self._notify()

    def update_all(self, snapshot: dict) -> None:
        """Обновить все процессы из снимка.

        Args:
            snapshot: dict[process_name, status_dict] — формат get_all_status().
        """
        for name, data in snapshot.items():
            existing = self._processes.get(name, {})
            self._processes[name] = {**existing, **data}
        logger.debug(
            "ProcessMonitorModel: обновлён полный снимок, процессов: %d", len(snapshot)
        )
        self._notify()

    def remove_process(self, name: str) -> None:
        """Удалить процесс из модели.

        Args:
            name: Имя процесса для удаления.
        """
        if name in self._processes:
            del self._processes[name]
            logger.debug("ProcessMonitorModel: удалён процесс %r", name)
            self._notify()

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def processes(self) -> dict:
        """Копия словаря всех процессов."""
        return dict(self._processes)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def add_change_callback(self, cb: Callable[[], None]) -> None:
        """Зарегистрировать callback для оповещения об изменениях.

        Args:
            cb: Вызываемый объект без аргументов.
        """
        self._callbacks.append(cb)

    def _notify(self) -> None:
        """Вызвать все зарегистрированные callbacks."""
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                logger.exception("ProcessMonitorModel: ошибка в callback")


__all__ = ["ProcessMonitorModel"]
