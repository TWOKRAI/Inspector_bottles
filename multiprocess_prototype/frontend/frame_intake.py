"""FrameIntake — цикл приёма IPC data-сообщений gui и метрики тракта кадров.

Purpose:
    Цикл приёма (раньше ``GuiProcess._data_receiver_loop``) стал методом ``run_loop``
    отдельного объекта с метриками тракта кадров. Воркер ``data_receiver`` создаётся на
    bound-методе ``FrameIntake.run_loop``: тогда ``WorkerManager.get_worker_status``
    подмешивает ``get_cycle_metrics()`` в статус воркера (и в heartbeat).

Public API:
    FrameIntake(receive, put, log_info, log_critical, track_error, record_metric, sleep=None, clock=None)
        .run_loop(stop_event, pause_event)   — цикл приёма (поток воркера)
        .get_cycle_metrics() -> dict         — ровно 10 ключей (см. класс); пик возраста не теряется
        .attach_pump_stats(provider)         — счётчики насоса: ``() -> {key: {...}}``
        .attach_mailbox_stats(provider)      — счётчики ящика: ``() -> dict`` (``LatestMailbox.stats``)
        .attach_qt_pending(provider)         — очередь Qt: ``() -> int``
    latency_sample(item, now) -> float | None
    fps_text(shown_per_s, superseded_per_s, per_slot) -> str

Thread-safety:
    ``run_loop`` пишет счётчики ``frames_in`` / ``batches`` из потока воркера;
    ``get_cycle_metrics`` читают разные потоки (heartbeat, ``get_status``, опрос состояния;
    чтение int ``frames_in`` / ``batches`` без замка безопасно под GIL). Состояние насосных
    метрик (окно возраста, база ``busy_ms_total``) защищено замком ``FrameIntake``. Провайдеры:
    ``FramePump.stats`` и ``LatestMailbox.stats`` берут снимок под своими замками,
    ``bridge.qt_pending`` читает два int без вызовов Qt.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from .bridge_impl import is_frame_message

_INITIAL_BACKOFF = 0.1  # начальный backoff (секунды)
_MAX_BACKOFF = 5.0
_ERROR_THRESHOLD = 5  # порог для вызова log_critical
_PAUSE_POLL_S = 0.05
_AGE_WINDOW_S = 5.0  # окно, за которое max_frame_age_ms хранит пик возраста кадра


def latency_sample(item: dict, now: float) -> float | None:
    """Сэмпл сквозной задержки кадра в мс: ``(now - capture_ts) * 1000``.

    ``capture_ts`` читается из ``item["data"]`` (source штампует ``time.time()`` при захвате).
    ``None``, если ``capture_ts`` нет или кадр помечен ``replay`` (в ``item`` либо в
    ``item["data"]``): воспроизведённый кадр показывается, но в статистику задержки не входит.
    """
    data = item.get("data")
    if not isinstance(data, dict):
        data = {}
    if item.get("replay") or data.get("replay"):
        return None
    capture_ts = data.get("capture_ts")
    if isinstance(capture_ts, bool) or not isinstance(capture_ts, (int, float)):
        return None
    return (now - capture_ts) * 1000.0


def fps_text(shown_per_s: float, superseded_per_s: float, per_slot: Mapping[str, float]) -> str:
    """Строка FPS: «показано» (всего и по слотам) и «вытеснено» в секунду.

    ``FPS: показано 22.0/с (main: 12.0, mask: 10.0), вытеснено 5.0/с``; без слотов скобок нет.
    """
    slots = ", ".join(f"{slot}: {rate:.1f}" for slot, rate in per_slot.items())
    shown = f"{shown_per_s:.1f}/с" + (f" ({slots})" if slots else "")
    return f"FPS: показано {shown}, вытеснено {superseded_per_s:.1f}/с"


class FrameIntake:
    """Цикл приёма data-сообщений и метрики тракта кадров.

    Колбэки внедряются (роли — как у ``GuiProcess``): ``receive`` =
    ``router_manager.receive``, ``put`` = ``bridge.dispatch``, остальные четыре —
    одноимённые методы процесса. ``sleep`` необязателен: по умолчанию зовётся
    ``time.sleep`` модуля (имя ``time`` разрешается при вызове).

    ``get_cycle_metrics`` отдаёт ровно 10 ключей: ``frames_in`` (сообщения-кадры, прошедшие
    ``is_frame_message``), ``batches`` (непустые ответы ``receive``), ``superseded`` /
    ``pending`` / ``bytes_held`` / ``max_bytes_held`` (из ``mailbox.stats()``), ``shown`` (сумма
    по ключам насоса), ``max_frame_age_ms`` (максимум ``window_max_age_ms`` по ключам),
    ``pump_busy_share`` (доля занятости насоса за интервал между вызовами), ``qt_pending``
    (передано в Qt минус обработано). До привязки провайдера его метрики равны 0.

    Читателей несколько (heartbeat, ``get_status``, опрос состояния: все зовут
    ``WorkerManager.get_worker_status``). ``max_frame_age_ms`` — максимум за последние
    ``_AGE_WINDOW_S`` секунд: каждый вызов сливает окно насоса (provider делает
    ``stats(reset_window=True)``) в скользящее окно ``FrameIntake``, поэтому второй читатель
    пик не отнимает у первого, а повторное чтение возвращает тот же пик. ``pump_busy_share`` —
    дельта ``busy_ms_total`` между двумя ЛЮБЫМИ последовательными вызовами; отношение к
    интервалу осмысленно для любого интервала, но интервалы делят между собой все читатели:
    частые чтения дают долю за короткий интервал (шумнее), не искажённую.
    """

    def __init__(
        self,
        receive: Callable[..., Any],
        put: Callable[[dict], Any],
        log_info: Callable[..., Any],
        log_critical: Callable[..., Any],
        track_error: Callable[..., Any],
        record_metric: Callable[..., Any],
        sleep: Callable[[float], Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._receive = receive
        self._put = put
        self._log_info = log_info
        self._log_critical = log_critical
        self._track_error = track_error
        self._record_metric = record_metric
        self._sleep = sleep
        self._clock = clock

        self._frames_in = 0
        self._batches = 0

        self._pump_stats: Callable[[], dict[str, dict[str, float]]] | None = None
        self._mailbox_stats: Callable[[], Mapping[str, int]] | None = None
        self._qt_pending: Callable[[], int] | None = None

        # Состояние дельты pump_busy_share: база busy_ms_total по ключам и момент её снятия.
        self._busy_base: dict[str, float] = {}
        self._busy_base_at: float | None = None
        # Окно пика возраста: пары (момент, window_max_age_ms насоса за период между вызовами).
        self._age_window: deque[tuple[float, float]] = deque()
        # Замок насосных метрик: get_cycle_metrics зовут несколько потоков.
        self._pump_lock = threading.Lock()

    # ------------------------------------------------------------------ привязки

    def attach_pump_stats(self, provider: Callable[[], dict[str, dict[str, float]]]) -> None:
        """Привязать счётчики насоса; ``provider()`` зовётся БЕЗ аргументов.

        Для ``FramePump`` provider — ``lambda: pump.stats(reset_window=True)``: окно
        ``window_max_age_ms`` сбрасывается тем же вызовом, что читает метрики.
        """
        self._pump_stats = provider

    def attach_mailbox_stats(self, provider: Callable[[], Mapping[str, int]]) -> None:
        """Привязать счётчики ящика («последний на ключ»): ``provider`` = ``mailbox.stats``."""
        self._mailbox_stats = provider

    def attach_qt_pending(self, provider: Callable[[], int]) -> None:
        """Привязать очередь Qt: ``provider() -> int`` (``bridge.qt_pending``)."""
        self._qt_pending = provider

    # ------------------------------------------------------------------ метрики

    def get_cycle_metrics(self) -> dict[str, float]:
        """Снять 10 метрик тракта кадров (см. docstring класса)."""
        mailbox = dict(self._mailbox_stats()) if self._mailbox_stats is not None else {}
        shown = 0
        max_frame_age_ms = 0.0
        busy_share = 0.0
        if self._pump_stats is not None:
            with self._pump_lock:
                pump = self._pump_stats()
                shown = sum(int(entry["shown"]) for entry in pump.values())
                max_frame_age_ms = self._windowed_max_age(pump)
                busy_share = self._busy_share(pump)
        return {
            "frames_in": self._frames_in,
            "batches": self._batches,
            "superseded": mailbox.get("superseded", 0),
            "pending": mailbox.get("pending", 0),
            "bytes_held": mailbox.get("bytes_held", 0),
            "max_bytes_held": mailbox.get("max_bytes_held", 0),
            "shown": shown,
            "max_frame_age_ms": max_frame_age_ms,
            "pump_busy_share": busy_share,
            "qt_pending": int(self._qt_pending()) if self._qt_pending is not None else 0,
        }

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    def _windowed_max_age(self, pump: Mapping[str, Mapping[str, float]]) -> float:
        """Слить окно насоса в скользящее окно и вернуть максимум за ``_AGE_WINDOW_S`` секунд. Замок взят."""
        now = self._now()
        period_max = max((float(entry["window_max_age_ms"]) for entry in pump.values()), default=0.0)
        self._age_window.append((now, period_max))
        while self._age_window and self._age_window[0][0] <= now - _AGE_WINDOW_S:
            self._age_window.popleft()
        return max(value for _, value in self._age_window)

    def _busy_share(self, pump: Mapping[str, Mapping[str, float]]) -> float:
        """Доля занятости насоса: дельта ``busy_ms_total`` за интервал между вызовами, зажим [0, 1].

        Дельта берётся ПО КЛЮЧУ с ``max(0, ...)``: ключ ушёл из ``set_keys`` (его счётчики
        удалены) или начался заново — вклад 0, а не отрицательная разность сумм. База
        снимается при первом вызове с провайдером и при первом появлении ключа (дельта
        нового ключа в том же вызове 0).
        """
        now = time.perf_counter()
        current = {key: float(entry["busy_ms_total"]) for key, entry in pump.items()}
        share = 0.0
        if self._busy_base_at is not None:
            interval_ms = (now - self._busy_base_at) * 1000.0
            if interval_ms > 0.0:
                delta_ms = sum(
                    max(0.0, busy - self._busy_base[key]) for key, busy in current.items() if key in self._busy_base
                )
                share = min(1.0, delta_ms / interval_ms)
        self._busy_base = current
        self._busy_base_at = now
        return share

    # ------------------------------------------------------------------ цикл приёма

    def _sleep_for(self, seconds: float) -> None:
        if self._sleep is not None:
            self._sleep(seconds)
        else:
            time.sleep(seconds)

    def run_loop(self, stop_event: Any, pause_event: Any) -> None:
        """Цикл получения IPC data-сообщений и передачи их в ``put`` (поток воркера)."""
        consecutive_errors = 0
        backoff = _INITIAL_BACKOFF

        while not stop_event.is_set():
            if pause_event.is_set():
                self._sleep_for(_PAUSE_POLL_S)
                continue
            try:
                # return_messages=False -> сырые dict (после middleware)
                msgs = self._receive(timeout=0.1, channel_types=["data"], return_messages=False)
                if msgs:
                    self._batches += 1
                for msg_dict in msgs:
                    self._put(msg_dict)
                    if is_frame_message(msg_dict):
                        self._frames_in += 1

                # При успешном получении - сбрасываем счётчик ошибок
                if msgs:
                    if consecutive_errors > 0:
                        self._log_info(
                            f"data_receiver: восстановление после {consecutive_errors} ошибок подряд",
                            module="gui",
                        )
                    consecutive_errors = 0
                    backoff = _INITIAL_BACKOFF
                    self._record_metric("data_receiver.success")

            except Exception as exc:
                consecutive_errors += 1

                # Трекинг через ErrorManager (единый паттерн)
                self._track_error(
                    exc,
                    context={
                        "loop": "data_receiver",
                        "consecutive": consecutive_errors,
                    },
                )

                # Метрика через StatsManager
                self._record_metric("data_receiver.errors")

                # После порога - critical лог
                if consecutive_errors == _ERROR_THRESHOLD:
                    self._log_critical(
                        f"data_receiver: {consecutive_errors} ошибок подряд, последняя: {exc}",
                        module="gui",
                    )

                # Exponential backoff
                self._sleep_for(min(backoff, _MAX_BACKOFF))
                backoff = min(backoff * 2, _MAX_BACKOFF)
