# -*- coding: utf-8 -*-
"""IdleWorker — generic воркер-цикл без полезной нагрузки.

Универсальный воркер для конструктора: крутит loop со smart-sleep на заданном
``target_interval_ms`` и измеряет фактический тайминг цикла (cycle_duration_ms /
effective_hz). Полезной нагрузки нет — её даёт Pipeline позже через подмену
``_do_work`` или замену класса воркера.

Используется как дефолтный target в worker.create, когда GUI создаёт воркер без
явного worker_class. Не зависит от multiprocess_prototype (резолвится по dotted-path
лоадером ``ProcessModule._create_workers_from_config`` или командой worker.create).

Smart-sleep по образцу generic/source_producer.py: спим порциями ≤10 мс, чтобы
быстро реагировать на ``stop_event``. Метрики читаются снаружи через
``get_cycle_metrics`` (WorkerManager.get_worker_status подмешивает их в статус →
heartbeat → ProcessMonitor → GUI).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .cycle_metrics import CycleMetricsRecorder

# Дефолтный интервал цикла, если target_interval_ms не задан (2 Гц).
_DEFAULT_INTERVAL_S = 0.5
# Максимальная порция сна — для отзывчивости на stop_event.
_SLEEP_CHUNK_S = 0.01


class IdleWorker:
    """Generic loop-воркер без нагрузки с измерением тайминга цикла.

    Args:
        process: объект процесса-владельца (ProcessModule / IProcessServices).
            Сейчас не используется (нагрузки нет), сохраняется для совместимости
            сигнатуры с другими воркерами и для будущего payload.
        config: dict конфигурации воркера. Распознаёт:
            - target_interval_ms: int — целевой интервал цикла (smart sleep)
            - execution_mode: "loop" | "task" — режим (task = один проход)
    """

    def __init__(self, process: Any = None, config: dict[str, Any] | None = None) -> None:
        self._process = process
        self._config = dict(config or {})

        interval_ms = self._config.get("target_interval_ms")
        if isinstance(interval_ms, (int, float)) and interval_ms > 0:
            self._target_interval = float(interval_ms) / 1000.0
        else:
            self._target_interval = _DEFAULT_INTERVAL_S

        self._execution_mode = str(self._config.get("execution_mode", "loop")).lower()

        # Телеметрия цикла — общий recorder (тот же контракт ключей, что у
        # SourceProducer/PipelineExecutor/DataReceiver).
        self._cycle_metrics = CycleMetricsRecorder(target_interval_s=self._target_interval)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def get_cycle_metrics(self) -> dict[str, Any]:
        """Снимок тайминга цикла (потокобезопасно).

        WorkerManager.get_worker_status подмешивает результат в статус воркера.
        """
        return self._cycle_metrics.get_cycle_metrics()

    def run(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Точка входа воркера (target для WorkerManager.create_worker).

        LOOP: крутит цикл до stop_event. TASK: один проход и выход.
        """
        if self._execution_mode == "task":
            self._run_once(stop_event, pause_event)
            return

        while not stop_event.is_set():
            if pause_event.is_set():
                # Пауза — не жжём CPU, быстро выходим по stop_event.
                stop_event.wait(0.05)
                continue
            self._run_once(stop_event, pause_event)

    # ------------------------------------------------------------------
    # Внутреннее
    # ------------------------------------------------------------------

    def _run_once(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Один цикл: работа + smart-sleep + запись тайминга."""
        t_start = time.monotonic()

        self._do_work()

        elapsed = time.monotonic() - t_start
        sleep_time = self._target_interval - elapsed
        if sleep_time > 0:
            deadline = time.monotonic() + sleep_time
            while time.monotonic() < deadline and not stop_event.is_set():
                time.sleep(max(0.0, min(_SLEEP_CHUNK_S, deadline - time.monotonic())))

        self._cycle_metrics.record(time.monotonic() - t_start)

    def _do_work(self) -> None:
        """Хук полезной нагрузки воркера.

        Сейчас no-op — нагрузку подключает Pipeline (подменой класса воркера или
        переопределением метода). Намеренно пустой.
        """
        # Полезная нагрузка появится в Pipeline-фазе.
        return None
