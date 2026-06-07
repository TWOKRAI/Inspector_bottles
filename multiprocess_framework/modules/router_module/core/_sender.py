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


# Sentinel для структурного завершения worker-потока.
# Кладётся в очередь с приоритетом -1 (ниже urgent=0) — worker
# заберёт его следующим и выйдет из цикла.
_SHUTDOWN = object()

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

    Выход worker-потока — СТРУКТУРНЫЙ: при stop() в очередь кладётся
    sentinel ``_SHUTDOWN`` с приоритетом -1 (ниже всех), worker забирает
    его блокирующим get() и завершается. join(timeout) — backstop на
    случай, если sentinel не дошёл (thread daemon, процесс завершится).

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
        """Структурно остановить worker-поток через poison-pill sentinel.

        1. Взводит stop_event (enqueue перестаёт принимать сообщения).
        2. Кладёт sentinel ``_SHUTDOWN`` с приоритетом -1 (ниже urgent=0) —
           worker заберёт его следующим при блокирующем get() и выйдет.
        3. join(timeout) — backstop: если sentinel не дошёл (например,
           очередь переполнена и put с timeout не успел), daemon-thread
           умрёт при завершении процесса.

        Гарантия вставки при полной очереди: используется блокирующий put
        с timeout. Worker дренирует очередь через send_fn → место
        освобождается. Если queue.Full всё же (крайний случай: send_fn
        блокирован дольше timeout) — логируем и полагаемся на join-timeout
        backstop.
        """
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            # Sentinel: приоритет -1 < urgent (0) → заберётся первым.
            # cnt из общего counter гарантирует уникальность кортежа →
            # heap НИКОГДА не сравнивает payload (третий элемент).
            try:
                self._queue.put((-1, next(self._counter), _SHUTDOWN), timeout=timeout)
            except queue.Full:
                self._log_warning(
                    "[AsyncSender] не удалось вставить sentinel (очередь полна) — полагаемся на join-timeout backstop"
                )
            self._thread.join(timeout=timeout)
        self._thread = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, msg_dict: Dict[str, Any], priority: str = "normal") -> None:
        """Положить сообщение в очередь. Никогда не блокируется.

        После вызова stop() новые сообщения не принимаются (no-op) —
        не копим работу в умирающую очередь.

        При переполнении буфера сообщение дропается с предупреждением.
        """
        if self._stop_event.is_set():
            return
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
        """Фоновый цикл: блокирующий get() + выход по sentinel.

        Блокировка внутри send_fn (полная IPC-очередь) не влияет на UI-поток.
        Выход — структурный: stop() кладёт sentinel _SHUTDOWN, worker
        забирает его и делает break. Ноль idle-CPU (блокирующий get,
        без polling/timeout). stop_event — доп. защита в условии цикла
        (backstop при аномальном пробуждении), но основной выход — sentinel.
        """
        while not self._stop_event.is_set():
            try:
                item = self._queue.get()
                _, _, msg = item
                if msg is _SHUTDOWN:
                    break
                self._send_fn(msg)
            except Exception as e:
                self._log_error(f"[AsyncSender] worker error: {e}")
