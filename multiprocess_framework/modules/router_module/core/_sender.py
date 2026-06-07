# -*- coding: utf-8 -*-
"""
AsyncSender — фоновый отправщик с приоритетной очередью.

Изолирует всю логику буферизации и отправки сообщений от RouterManager.
Принимает send_fn (callable) — функцию фактической отправки в канал.
RouterManager передаёт туда свой _do_send().

Жизненный цикл:
    sender = AsyncSender("router_name", do_send_fn=router._do_send)
    sender.start()
    sender.enqueue(msg, priority="high")
    sender.stop()
"""

import itertools
import queue
import threading
from typing import Any, Callable, Dict, Optional


# Числовые приоритеты (меньше = важнее)
PRIORITY_MAP: Dict[str, int] = {
    "urgent": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}
DEFAULT_PRIORITY = 2  # normal


class AsyncSender:
    """Буферизованный неблокирующий отправщик.

    Хранит исходящие сообщения в PriorityQueue и обрабатывает их в
    фоновом потоке, вызывая переданную send_fn(msg_dict).

    Это позволяет UI-потоку вызывать enqueue() мгновенно, даже если
    канал доставки (IPC-очередь, сокет) временно занят или недоступен.

    Attrs:
        queued  — сколько сообщений помещено в буфер
        dropped — сколько отброшено из-за переполнения буфера
    """

    def __init__(
        self,
        name: str,
        send_fn: Callable[[Dict[str, Any]], Any],
        queue_size: int = 512,
        log_warning: Optional[Callable] = None,
        log_error: Optional[Callable] = None,
    ) -> None:
        self._name = name
        self._send_fn = send_fn
        self._queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=queue_size)
        self._counter = itertools.count()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._log_warning = log_warning or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)

        self.queued: int = 0
        self.dropped: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Запустить фоновый поток-отправщик."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker,
            name=f"router-sender-{self._name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Остановить поток. Ждёт завершения текущей отправки.

        Timeout снижен с 3.0 → 1.0: worker-цикл проверяет stop_event каждые 10ms
        (queue.get timeout=0.01), поэтому join завершается практически мгновенно.
        3с были избыточны и складывались с cap.release() (~1-2с на DirectShow),
        создавая суммарную задержку > 5с → принудительный terminate процессов.
        """
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, msg_dict: Dict[str, Any], priority: str = "normal") -> None:
        """Положить сообщение в очередь. Никогда не блокируется.

        При переполнении буфера сообщение дропается с предупреждением.
        """
        prio_int = PRIORITY_MAP.get(priority.lower(), DEFAULT_PRIORITY)
        try:
            self._queue.put_nowait((prio_int, next(self._counter), msg_dict))
            self.queued += 1
        except queue.Full:
            self.dropped += 1
            self._log_warning(
                f"[AsyncSender] buffer full — dropped "
                f"channel={msg_dict.get('channel')!r} "
                f"command={msg_dict.get('command')!r}"
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Фоновый цикл: достаёт сообщения и передаёт в send_fn.

        Блокировка внутри send_fn (полная IPC-очередь) не влияет на UI-поток.
        timeout=0.01: частая проверка stop_event обеспечивает быстрый выход (~10ms)
        при shutdown — критично для укладки в 5с OS-deadline при recipe hot-swap.
        """
        while not self._stop_event.is_set():
            try:
                _, _, msg_dict = self._queue.get(timeout=0.01)
                self._send_fn(msg_dict)
            except queue.Empty:
                continue
            except Exception as e:
                self._log_error(f"[AsyncSender] worker error: {e}")
