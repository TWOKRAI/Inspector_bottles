# -*- coding: utf-8 -*-
"""
AsyncReceiver — фоновый приёмник сообщений с системой колбэков.

Изолирует логику listener-потока и управления колбэками от RouterManager.
Принимает receive_fn (callable) — функцию получения сообщений из каналов.
RouterManager передаёт туда свой receive().

Жизненный цикл:
    receiver = AsyncReceiver("router_name")
    receiver.add_callback(on_message)
    receiver.start(receive_fn=router.receive, poll_interval=0.01)
    ...
    receiver.stop()
"""

import threading
import time
from typing import Callable, List, Optional


class AsyncReceiver:
    """Фоновый приёмник сообщений.

    Запускает daemon-поток, который периодически вызывает receive_fn(),
    а затем передаёт каждое сообщение всем зарегистрированным колбэкам.

    Колбэки защищены RLock — их можно добавлять и удалять из любого потока
    во время работы listener'а без риска race condition.

    Attrs:
        processed — сколько сообщений передано колбэкам
        errors    — сколько ошибок в колбэках + worker
    """

    def __init__(
        self,
        name: str,
        log_warning: Optional[Callable] = None,
        log_error: Optional[Callable] = None,
        log_info: Optional[Callable] = None,
    ) -> None:
        self._name = name
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._lock = threading.RLock()
        self._callbacks: List[Callable] = []

        self._log_warning = log_warning or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)
        self._log_info = log_info or (lambda msg: None)

        self.processed: int = 0
        self.errors: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, receive_fn: Callable, poll_interval: float = 0.01) -> bool:
        """Запустить фоновый listener-поток.

        Args:
            receive_fn:    Функция получения сообщений (router.receive).
            poll_interval: Пауза между опросами в секундах.

        Returns:
            False если поток уже запущен.
        """
        if self._thread and self._thread.is_alive():
            self._log_warning("[AsyncReceiver] listener already running")
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker,
            args=(receive_fn, poll_interval),
            name=f"router-listener-{self._name}",
            daemon=True,
        )
        self._thread.start()
        self._log_info("[AsyncReceiver] listener started")
        return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Остановить listener-поток."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        return True

    # ------------------------------------------------------------------
    # Callback management
    # ------------------------------------------------------------------

    def add_callback(self, callback: Callable) -> None:
        """Зарегистрировать колбэк. Вызывается для каждого входящего сообщения."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        """Удалить колбэк."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def clear_callbacks(self) -> None:
        """Удалить все колбэки."""
        with self._lock:
            self._callbacks.clear()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def callback_count(self) -> int:
        with self._lock:
            return len(self._callbacks)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _worker(self, receive_fn: Callable, poll_interval: float) -> None:
        """Фоновый цикл: получает сообщения и вызывает колбэки."""
        while not self._stop_event.is_set():
            try:
                messages = receive_fn(return_messages=True)

                # Снимаем snapshot колбэков под lock'ом —
                # чтобы не держать lock во время вызова колбэков.
                with self._lock:
                    cbs = list(self._callbacks)

                for msg in messages:
                    self.processed += 1
                    for cb in cbs:
                        try:
                            cb(msg)
                        except Exception as e:
                            self.errors += 1
                            self._log_error(f"[AsyncReceiver] callback error: {e}")

                time.sleep(poll_interval)

            except Exception as e:
                self.errors += 1
                self._log_error(f"[AsyncReceiver] worker error: {e}")
                time.sleep(1.0)
