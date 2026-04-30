"""ProcessDataBridge — мост между шиной сообщений и ProcessMonitorModel.

Отвечает за:
- Приём broadcast о смене статуса процессов (process_status_changed)
- Приём broadcast полного снимка (process_full_status)
- Polling-запросы к ProcessManager для получения полного снимка
- Управление QTimer для периодического polling
- Singleton-паттерн для доступа из GuiProcess без прямой ссылки
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Глобальный singleton: ссылка на активный экземпляр bridge
_active_bridge: ProcessDataBridge | None = None


def get_active_bridge() -> ProcessDataBridge | None:
    """Получить активный экземпляр bridge (singleton).

    Returns:
        Активный ProcessDataBridge или None если не создан.
    """
    return _active_bridge


class ProcessDataBridge:
    """Мост данных мониторинга процессов.

    Связывает внешний источник данных (ProcessManager, broadcast)
    с ProcessMonitorModel. Поддерживает:
    - push от ProcessMonitor (process_status_changed / process_full_status)
    - polling через QTimer как fallback

    Singleton: регистрирует себя при создании, снимает при stop_polling().
    """

    def __init__(
        self,
        model: Any,
        command_handler: Any | None = None,
    ) -> None:
        """Инициализировать bridge и зарегистрировать как singleton.

        Args:
            model:           ProcessMonitorModel для обновления данных.
            command_handler: RoutedCommandSender для отправки команд.
        """
        global _active_bridge
        self._model = model
        self._command_handler = command_handler
        self._timer: Any | None = None
        _active_bridge = self

    # ------------------------------------------------------------------
    # Приём broadcast от ProcessMonitor
    # ------------------------------------------------------------------

    def on_status_update(self, msg: dict) -> None:
        """Обработать broadcast о смене статуса процесса.

        Ожидаемый формат msg (process_status_changed):
            {
                "type":         "system",
                "subtype":      "process_status_changed",
                "sender":       str,
                "process_name": str,
                "old_status":   str,
                "new_status":   str,
                "state":        dict,  # {status, metadata, custom, ...}
                "timestamp":    float,
            }

        Args:
            msg: Словарь broadcast-сообщения.
        """
        process_name = msg.get("process_name")
        new_status = msg.get("new_status", "unknown")
        state = msg.get("state", {})

        if not process_name:
            logger.warning(
                "ProcessDataBridge.on_status_update: отсутствует process_name в msg=%r", msg
            )
            return

        # workers попадают в update_data через **state, если ProcessMonitor
        # обогатил state данными о воркерах (см. process_monitor._broadcast_status_change)
        update_data = {"status": new_status, **state}
        self._model.update_process(process_name, update_data)
        logger.debug(
            "ProcessDataBridge: обновлён статус %r -> %r", process_name, new_status
        )

    def on_full_snapshot(self, snapshot: dict) -> None:
        """Обработать полный снимок состояния всех процессов.

        Args:
            snapshot: dict[process_name, status_dict] — формат get_all_status().
        """
        if not snapshot or not isinstance(snapshot, dict):
            return
        # workers попадают в модель через merge {**existing, **data} в update_all,
        # поскольку ProcessMonitor включает workers в данные каждого процесса
        # (см. process_monitor._broadcast_full_status)
        self._model.update_all(snapshot)
        logger.debug(
            "ProcessDataBridge: загружен полный снимок, процессов: %d", len(snapshot)
        )

    # ------------------------------------------------------------------
    # Запрос полного снимка
    # ------------------------------------------------------------------

    def request_full_snapshot(self) -> None:
        """Запросить полный снимок через process.command wrapper (process.list)."""
        if self._command_handler is not None:
            try:
                data = {"cmd": "process.list", "correlation_id": str(uuid.uuid4())}
                self._command_handler.send("process.command", data=data)
                logger.debug("ProcessDataBridge: отправлен process.list через process.command")
            except Exception:
                logger.debug("ProcessDataBridge: не удалось отправить process.list")

    # ------------------------------------------------------------------
    # Polling через QTimer
    # ------------------------------------------------------------------

    def start_polling(self, parent_widget: Any) -> None:
        """Запустить периодический polling запросов.

        Создаёт QTimer с интервалом 5 секунд, который вызывает
        request_full_snapshot(). Таймер привязан к parent_widget
        для корректного управления временем жизни.

        Args:
            parent_widget: Родительский QWidget (владелец таймера).
        """
        from PySide6.QtCore import QTimer

        self._timer = QTimer(parent_widget)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.request_full_snapshot)
        self._timer.start()
        logger.debug("ProcessDataBridge: polling запущен (интервал 5с)")

    def stop_polling(self) -> None:
        """Остановить polling таймер и снять singleton-регистрацию."""
        global _active_bridge
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
            logger.debug("ProcessDataBridge: polling остановлен")
        _active_bridge = None


__all__ = ["ProcessDataBridge", "get_active_bridge"]
