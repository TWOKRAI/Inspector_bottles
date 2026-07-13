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
from typing import Callable

from . import frame_trace
from .cycle_metrics import CycleMetricsRecorder
from ...router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from .inspector_registry import ItemInspector


class DataReceiver:
    """Приём data-plane IPC → item → InspectorManager → chain_queue.

    Args:
        receive_fn: callable для получения IPC сообщений (process.receive_message)
        shm_middleware: FrameShmMiddleware для восстановления frame из SHM
        inspector_manager: ItemInspector (буфер fan-in/join, DI из Plugins/_shared/fanin)
        chain_queue: очередь для готовых коллекций items → PipelineExecutor
        lag_alert_threshold_sec: порог для backpressure alert (Q6)
        log_info: callback для логирования
        log_error: callback для ошибок
    """

    def __init__(
        self,
        receive_fn: Callable,
        shm_middleware: FrameShmMiddleware | None,
        inspector_manager: ItemInspector,
        chain_queue: queue.Queue,
        lag_alert_threshold_sec: float = 2.0,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
        log_debug: Callable[[str], None] | None = None,
        node_name: str = "",
    ) -> None:
        self._receive = receive_fn
        # Имя процесса-узла — для frame-trace transport-спана (from -> node).
        self._node = node_name
        self._shm = shm_middleware
        self._inspector = inspector_manager
        self._chain_queue = chain_queue
        self._lag_threshold = lag_alert_threshold_sec
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)
        # [TRACE] per-frame диагностика → DEBUG (не флудить INFO-консоль). Дефолт —
        # общий kwargs-safe no-op (F6d, ревью 2026-07-13): вызов ниже несёт
        # trace_id=... как extra для LogRecord (Ф7 G.6) — реальные
        # ProcessModule._log_debug тоже kwargs-safe.
        self._log_debug = log_debug or frame_trace.noop_log

        # Метрики
        self._overload_events = 0
        self._last_timeout_check = 0.0

        # Тайминг цикла приёма для телеметрии GUI. Воркер receive-driven:
        # меряем только итерации с реально полученным сообщением, а не
        # холостые spin'ы при пустом receive (иначе effective_hz отражал бы
        # частоту опроса, а не реальный поток данных).
        self._cycle_metrics = CycleMetricsRecorder(target_interval_s=0.0)

        # stop_event текущего run_loop — сохраняется при запуске воркера,
        # используется в on_items_ready для stop-aware backpressure.
        self._stop_event: threading.Event | None = None

    def get_cycle_metrics(self) -> dict:
        """Снимок тайминга цикла приёма (потокобезопасно).

        WorkerManager.get_worker_status подмешивает результат в статус воркера →
        heartbeat → ProcessMonitor.state.fps/latency_ms → GUI.
        """
        return self._cycle_metrics.get_cycle_metrics()

    def on_items_ready(self, items: list[dict]) -> None:
        """Callback от InspectorManager — коллекция готова, кладём в chain_queue.

        Backpressure (Q6): block + alert. Никогда не дропаем в нормальной работе.

        При взведённом stop_event (shutdown) — прекращаем ожидание освобождения
        очереди: downstream consumer уже остановлен, ждать бессмысленно. Item
        дропается (единственный случай) чтобы воркер мог выйти gracefully.
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
            # Stop-aware backpressure: chunked put с проверкой stop_event.
            # В нормальной работе блокируем до освобождения (Q6 — не дропаем).
            # При shutdown (stop_event взведён) — выходим, чтобы не зависнуть:
            # downstream consumer уже гасится и очередь никто не дочитает.
            while True:
                if self._stop_event is not None and self._stop_event.is_set():
                    # Downstream остановлен — дропаем и выходим (shutdown path)
                    self._log_error("DataReceiver: stop_event set during backpressure wait — dropping item (shutdown)")
                    return
                try:
                    self._chain_queue.put(items, timeout=0.1)
                    return  # успешно положили
                except queue.Full:
                    continue  # ещё не освободилась — проверим stop_event снова

    def run_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """LOOP worker: receive IPC → restore frame → InspectorManager.

        Args:
            stop_event: сигнал остановки
            pause_event: сигнал паузы
        """
        # Сохраняем stop_event для on_items_ready (stop-aware backpressure).
        self._stop_event = stop_event
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

            # Тайминг полезной итерации (restore + build + on_item), без учёта
            # ожидания на пустом receive. perf_counter (не monotonic): работа
            # subмиллисекундная, а monotonic на Windows имеет ~15мс гранулярность.
            t_start = time.perf_counter()

            # Message → dict: middleware и pipeline работают с plain dict
            if hasattr(msg, "to_dict"):
                msg = msg.to_dict()

            # [TRACE] Логируем каждый 30-й приём
            if not hasattr(self, "_trace_recv_cnt"):
                self._trace_recv_cnt = 0
            self._trace_recv_cnt += 1
            do_trace = self._trace_recv_cnt % 30 == 1

            if do_trace:
                data = msg.get("data", {})
                self._log_debug(
                    f"[TRACE] DataReceiver: msg received, "
                    f"data_type={msg.get('data_type', '?')}, "
                    f"sender={msg.get('sender', '?')}, "
                    f"has_shm_name={bool(data.get('shm_name') if isinstance(data, dict) else False)}, "
                    f"has_frame={'frame' in msg}"
                )

            # Восстановить frame из SHM
            if self._shm:
                msg = self._shm.restore_frame(msg)

            if do_trace:
                self._log_debug(
                    f"[TRACE] DataReceiver: after restore_frame, has_frame={'frame' in msg}, "
                    f"frame_is_none={msg.get('frame') is None if 'frame' in msg else 'N/A'}"
                )

            # Построить item из msg
            item = self._build_item(msg)

            # frame-trace: время передачи от предыдущего узла к этому.
            frame_trace.record_transport(item, self._node)

            if do_trace:
                frame = item.get("frame")
                shape = frame.shape if frame is not None and hasattr(frame, "shape") else None
                # Ф7 G.6: trace_id проброшен из источника вместе с item (Dict at
                # Boundary, поле пережило SHM/pickle round-trip само по себе) —
                # звено 2 (приёмный узел), позволяет коррелировать лог с логом
                # источника по одному trace_id.
                self._log_debug(
                    f"[TRACE] DataReceiver: item built, "
                    f"has_frame={'frame' in item}, shape={shape}, "
                    f"total_regions={item.get('total_regions', 0)}, "
                    f"seq_id={item.get('seq_id')}",
                    trace_id=item.get("trace_id"),
                )

            # Передать в InspectorManager
            self._inspector.on_item(item)

            # Полный цикл обработки одного сообщения → телеметрия.
            self._cycle_metrics.record(time.perf_counter() - t_start)

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

        # Стандартные поля из msg-уровня.
        # sender/data_type — для корреляции в JoinInspectorManager (Этап 1) и io-debug:
        # sender ставится на msg-уровне (process_communication.send_to_process) и иначе
        # потерялся бы при build; data_type помечает поток (frame/overlay/detections/...).
        for key in (
            "camera_id",
            "seq_id",
            "total_regions",
            "region_name",
            "frame_id",
            "timestamp",
            "owner",
            "shm_name",
            "shm_index",
            "sender",
            "data_type",
        ):
            if key in msg and key not in item:
                item[key] = msg[key]

        return item

    @property
    def overload_events(self) -> int:
        """Количество событий backpressure overload."""
        return self._overload_events
