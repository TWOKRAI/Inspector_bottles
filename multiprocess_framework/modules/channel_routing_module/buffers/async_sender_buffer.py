# -*- coding: utf-8 -*-
"""
AsyncSenderBuffer — буферная стратегия с приоритетной очередью и фоновым потоком.

Адаптация router_module/core/_sender.py (AsyncSender) к интерфейсу IBufferStrategy.
Подходит для RouterManager и других менеджеров с требованиями к приоритизации.

Принцип:
    enqueue() никогда не блокируется — помещает (priority, seq, channel, data) в
    PriorityQueue. Фоновый поток извлекает элементы и вызывает send_fn(channel, data).

Thread safety:
    PriorityQueue потокобезопасен. enqueue() и stop() можно вызывать из любого потока.

Priority mapping:
    "urgent" → 0 (наивысший)
    "high"   → 1
    "normal" → 2 (по умолчанию)
    "low"    → 3
"""
import itertools
import queue
import threading
from typing import Any, Callable, Dict, Optional

from ..interfaces import IBufferStrategy


PRIORITY_MAP: Dict[str, int] = {
    "urgent": 0,
    "high":   1,
    "normal": 2,
    "low":    3,
}
DEFAULT_PRIORITY = 2  # "normal"


class AsyncSenderBuffer(IBufferStrategy):
    """Неблокирующая буферная стратегия с приоритетной очередью.

    Пример использования:
        def _do_write(channel_name: str, data: dict) -> None:
            registry.get(channel_name).write(data)

        buf = AsyncSenderBuffer(send_fn=_do_write, queue_size=512)
        buf.start()
        buf.enqueue("logs", {"level": "INFO", "message": "..."}, priority="normal")
        buf.stop()
    """

    def __init__(
        self,
        send_fn: Callable[[str, Dict[str, Any]], Any],
        queue_size: int = 512,
        log_warning: Optional[Callable] = None,
        log_error:   Optional[Callable] = None,
    ) -> None:
        """
        Args:
            send_fn:    fn(channel_name: str, data: Dict) → Any
            queue_size: Максимальный размер PriorityQueue. При переполнении
                        сообщение дропается (с предупреждением).
            log_warning: Callable для предупреждений (иначе тихо)
            log_error:   Callable для ошибок (иначе тихо)
        """
        self._send_fn    = send_fn
        self._queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=queue_size)
        self._counter    = itertools.count()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._log_warning = log_warning or (lambda msg: None)
        self._log_error   = log_error   or (lambda msg: None)

        self._enqueued: int = 0
        self._dropped:  int = 0
        self._sent:     int = 0
        self._errors:   int = 0

    # ------------------------------------------------------------------
    # IBufferStrategy — lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Запустить фоновый поток-отправщик."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker,
            name="async-sender-buffer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Остановить фоновый поток (ждёт завершения текущей отправки)."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    # ------------------------------------------------------------------
    # IBufferStrategy — enqueue / flush
    # ------------------------------------------------------------------

    def enqueue(self, channel: str, data: Dict[str, Any], priority: str = "normal") -> None:
        """Поместить данные в очередь. Никогда не блокируется.

        При переполнении очереди данные дропаются с предупреждением.
        """
        prio_int = PRIORITY_MAP.get(priority.lower(), DEFAULT_PRIORITY)
        try:
            self._queue.put_nowait((prio_int, next(self._counter), channel, data))
            self._enqueued += 1
        except queue.Full:
            self._dropped += 1
            self._log_warning(
                f"[AsyncSenderBuffer] queue full — dropped "
                f"channel={channel!r} priority={priority!r}"
            )

    def flush(self, channel: Optional[str] = None) -> None:
        """Принудительного flush нет — данные обрабатываются фоновым потоком.

        Для синхронного ожидания используйте stop() + start().
        channel=None → флаг игнорируется.
        """

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        """True если фоновый поток работает."""
        return bool(self._thread and self._thread.is_alive())

    @property
    def qsize(self) -> int:
        """Текущий размер очереди."""
        return self._queue.qsize()

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "type":     "async_sender",
            "enqueued": self._enqueued,
            "dropped":  self._dropped,
            "sent":     self._sent,
            "errors":   self._errors,
            "qsize":    self.qsize,
            "running":  self.is_alive,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Фоновый цикл: извлекает элементы из очереди и вызывает send_fn."""
        while not self._stop_event.is_set():
            try:
                _, _, ch_name, data = self._queue.get(timeout=0.1)
                try:
                    self._send_fn(ch_name, data)
                    self._sent += 1
                except Exception as e:
                    self._errors += 1
                    self._log_error(f"[AsyncSenderBuffer] send_fn error channel={ch_name!r}: {e}")
            except queue.Empty:
                continue
            except Exception as e:
                self._errors += 1
                self._log_error(f"[AsyncSenderBuffer] worker error: {e}")
