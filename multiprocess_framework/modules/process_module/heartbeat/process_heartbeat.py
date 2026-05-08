"""ProcessHeartbeat — отправка периодических heartbeat-сообщений ProcessManager-у."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..plugins.interfaces import IProcessServices


class ProcessHeartbeat:
    """Heartbeat sender через IProcessServices.

    Отправляет периодические heartbeat-сообщения в ProcessManager
    для мониторинга состояния процесса.
    """

    def __init__(self, services: Any) -> None:
        """
        Args:
            services: объект удовлетворяющий IProcessServices
        """
        self._services = services
        self._interval: float = 5.0

    def start(self) -> None:
        """Создать и запустить heartbeat воркер если включён в конфиге."""
        interval = self._services.get_config("heartbeat_interval", 5.0)
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = 5.0

        if interval <= 0:
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log("Heartbeat отключён (heartbeat_interval <= 0)", module="heartbeat")
            return

        if not self._services.worker_manager:
            return

        from ...worker_module import ThreadConfig, ThreadPriority

        self._interval = interval
        self._services.worker_manager.create_worker(
            "heartbeat_sender",
            self._loop,
            ThreadConfig(priority=ThreadPriority.BACKGROUND),
            auto_start=True,
        )
        _log = getattr(self._services, "log_debug", self._services.log_info)
        _log(
            f"Heartbeat воркер запущен (interval={interval}с)",
            module="heartbeat",
        )

    def _loop(self, stop_event, pause_event) -> None:
        """Цикл отправки heartbeat-сообщений."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                heartbeat_msg = {
                    "type": "system",
                    "subtype": "heartbeat",
                    "command": "heartbeat",
                    "sender": self._services.name,
                    "timestamp": time.time(),
                    "status": getattr(self._services, "_current_process_status", "running"),
                }
                # Данные о воркерах для ProcessMonitor
                # Dict at Boundary: get_all_workers_status() уже возвращает чистые dict
                if self._services.worker_manager:
                    get_status = getattr(
                        self._services.worker_manager, "get_all_workers_status", None
                    )
                    if get_status is not None:
                        try:
                            workers = get_status()
                            # Исключаем metrics для экономии трафика IPC
                            for w in workers.values():
                                w.pop("metrics", None)
                            heartbeat_msg["workers_status"] = workers
                        except Exception:
                            pass
                self._services.send_message("ProcessManager", heartbeat_msg)
            except Exception as exc:
                _log = getattr(self._services, "log_debug", self._services.log_info)
                _log(f"Не удалось отправить heartbeat: {exc}", module="heartbeat")
            # Ожидание с проверкой stop_event для быстрого завершения
            stop_event.wait(timeout=self._interval)
