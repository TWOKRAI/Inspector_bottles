"""DataReceiver — компонент приёма IPC и трансформации в items.

Receive loop:
  IPC msg → FrameShmMiddleware.restore_frame() → item → InspectorManager.on_item()
  Периодически: InspectorManager.check_timeouts()

Используется GenericProcess как LOOP worker.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

from .frame_shm_middleware import FrameShmMiddleware
from .inspector_manager import InspectorManager


class DataReceiver:
    """Приём data-plane IPC → item → InspectorManager → chain_queue.

    Args:
        receive_fn: callable для получения IPC сообщений (process.receive_message)
        shm_middleware: FrameShmMiddleware для восстановления frame из SHM
        inspector_manager: InspectorManager для буферизации fan-in
        chain_queue: очередь для готовых коллекций items → PipelineExecutor
        lag_alert_threshold_sec: порог для backpressure alert (Q6)
        log_info: callback для логирования
        log_error: callback для ошибок
    """

    def __init__(
        self,
        receive_fn: Callable,
        shm_middleware: FrameShmMiddleware | None,
        inspector_manager: InspectorManager,
        chain_queue: queue.Queue,
        lag_alert_threshold_sec: float = 2.0,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._receive = receive_fn
        self._shm = shm_middleware
        self._inspector = inspector_manager
        self._chain_queue = chain_queue
        self._lag_threshold = lag_alert_threshold_sec
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)

        # Метрики
        self._overload_events = 0
        self._last_timeout_check = 0.0

    def on_items_ready(self, items: list[dict]) -> None:
        """Callback от InspectorManager — коллекция готова, кладём в chain_queue.

        Backpressure (Q6): block + alert. Никогда не дропаем.
        """
        try:
            self._chain_queue.put(items, timeout=self._lag_threshold)
        except queue.Full:
            # Алерт: pipeline overload
            self._overload_events += 1
            self._log_error(
                f"DataReceiver: pipeline overload (queue full > {self._lag_threshold}s), "
                f"events={self._overload_events}. Ждём освобождения..."
            )
            # Блокируем до освобождения — НИКОГДА не дропаем (Q6)
            self._chain_queue.put(items)

    def run_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """LOOP worker: receive IPC → restore frame → InspectorManager.

        Args:
            stop_event: сигнал остановки
            pause_event: сигнал паузы
        """
        self._last_timeout_check = time.monotonic()

        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Периодическая проверка timeouts (каждые ~100ms)
            now = time.monotonic()
            if now - self._last_timeout_check > 0.1:
                self._inspector.check_timeouts()
                self._last_timeout_check = now

            # Receive IPC с timeout
            msg = self._receive(timeout=0.05, channel_types=["data"])
            if msg is None:
                continue

            # Восстановить frame из SHM
            if self._shm:
                msg = self._shm.restore_frame(msg)

            # Построить item из msg
            item = self._build_item(msg)

            # Передать в InspectorManager
            self._inspector.on_item(item)

    def _build_item(self, msg: dict) -> dict:
        """Построить item из IPC сообщения.

        Извлекает data-поля из msg, сохраняет frame.
        """
        # msg может содержать "data" dict или быть flat
        data = msg.get("data", {})
        if isinstance(data, dict):
            item = dict(data)
        else:
            item = {}

        # frame восстановлен SHM middleware и лежит в msg["frame"]
        if "frame" in msg:
            item["frame"] = msg["frame"]

        # Стандартные поля из msg-уровня
        for key in ("camera_id", "seq_id", "total_regions", "region_name",
                    "frame_id", "timestamp", "owner", "shm_name", "shm_index"):
            if key in msg and key not in item:
                item[key] = msg[key]

        return item

    @property
    def overload_events(self) -> int:
        """Количество событий backpressure overload."""
        return self._overload_events
