# -*- coding: utf-8 -*-
"""
QueueChannel — канал поверх multiprocessing.Queue / queue.Queue.

Поддерживает:
  - Синхронную отправку с таймаутом (не блокирует навсегда при занятом consumer'е).
  - Non-blocking и blocking poll.
  - Опциональный фоновый listen-поток с callback.
  - Инъекцию log-колбэков от RouterManager (через MessageChannel._attach_logger).

Создание:
    ch = QueueChannel("ctrl", mp_queue)
    ch = QueueChannel("ctrl")          # создаёт внутренний queue.Queue
"""

import threading
import time
from queue import Queue, Empty, Full
from typing import Callable, Dict, Any, List, Optional

from .base_channel import MessageChannel


class QueueChannel(MessageChannel):
    """Канал сообщений на основе Queue (queue.Queue или multiprocessing.Queue)."""

    def __init__(
        self,
        name: str,
        queue: Optional[Queue] = None,
        log_warning: Optional[Callable[[str], None]] = None,
        log_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(log_warning=log_warning, log_error=log_error)
        self._name = name
        self._queue = queue if queue is not None else Queue()
        self._listening = False
        self._listener_thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable] = None
        # План transport-single-policy (Task 0.1). Этот канал кладёт в очередь БЕЗ
        # QoS-политики: полная очередь = ожидание до timeout, затем ошибка (по сути
        # drop_newest), тогда как QueueRegistry.send_to_queue вытеснил бы старейший
        # и сообщил владельцу кадра. Пока обе двери живы — переполнение здесь должно
        # быть видно, иначе перегрузка тракта не наблюдаема ничем.
        self._put_timeout_total = 0
        self._send_errors = 0

    # ---- IMessageChannel: свойства ----

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "queue"

    # ---- IMessageChannel: отправка ----

    def send(self, message: Dict[str, Any], timeout: float = 1.0) -> Dict[str, Any]:
        """Положить сообщение в очередь.

        Args:
            message: Словарь-сообщение.
            timeout: Максимальное ожидание (сек) если очередь полная.
                     1 сек по умолчанию — не блокирует навсегда при упавшем consumer'е.

        Returns:
            {"status": "success", "channel": name} или {"status": "error", "reason": ...}
        """
        try:
            self._queue.put(message, block=True, timeout=timeout)
            return {"status": "success", "channel": self._name}
        except Full:
            # Очередь была полна весь timeout — сообщение ПОТЕРЯНО. Отдельный счётчик:
            # это перегрузка тракта, а не сбой канала, и лечится она политикой
            # (drop_oldest), а не ретраем. Раньше терялось молча в общем "errors".
            self._put_timeout_total += 1
            self._send_errors += 1
            return {"status": "error", "reason": "queue full (put timeout)", "channel": self._name}
        except Exception as e:
            self._send_errors += 1
            return {"status": "error", "reason": str(e), "channel": self._name}

    # ---- IMessageChannel: получение ----

    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Опросить очередь.

        Args:
            timeout: 0 → non-blocking drain (все доступные сообщения).
                     >0 → блокирующий вызов, ждёт одно сообщение.

        Returns:
            Список сообщений (может быть пустым).
        """
        messages: List[Dict[str, Any]] = []
        try:
            if timeout > 0:
                msg = self._queue.get(timeout=timeout)
                if msg is not None:
                    messages.append(msg)
            else:
                while True:
                    try:
                        msg = self._queue.get_nowait()
                        if msg is not None:
                            messages.append(msg)
                    except Empty:
                        break
        except Empty:
            pass
        except Exception as e:
            self._log_error(f"[QueueChannel:{self._name}] poll error: {e}")
        return messages

    # ---- Асинхронное прослушивание ----

    def start_listening(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """Запустить фоновый поток, который вызывает callback для каждого сообщения.

        Returns:
            False если уже запущен.
        """
        if self._listening:
            return False
        self._callback = callback
        self._listening = True
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            name=f"queue-ch-{self._name}",
            daemon=True,
        )
        self._listener_thread.start()
        return True

    def stop_listening(self) -> bool:
        """Остановить фоновый поток."""
        self._listening = False
        if self._listener_thread:
            self._listener_thread.join(timeout=1.0)
            self._listener_thread = None
        return True

    # ---- Мониторинг ----

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        try:
            queue_size = self._queue.qsize()
        except (NotImplementedError, OSError, AttributeError):
            queue_size = None
        info.update(
            {
                "queue_size": queue_size,
                "listening": self._listening,
                "put_timeout_total": self._put_timeout_total,
                "send_errors": self._send_errors,
            }
        )
        return info

    # ---- Счётчики двери (Task 0.1) — read-only проекция для RouterManager.get_stats ----

    @property
    def put_timeout_total(self) -> int:
        """Сколько сообщений потеряно из-за полной очереди (put упёрся в timeout)."""
        return self._put_timeout_total

    @property
    def send_errors(self) -> int:
        """Все неудачные отправки канала, включая put_timeout_total."""
        return self._send_errors

    # ---- Внутреннее ----

    def _listen_loop(self) -> None:
        while self._listening:
            try:
                for msg in self.poll(timeout=0.1):
                    if self._callback:
                        self._callback(msg)
            except Exception as e:
                self._log_error(f"[QueueChannel:{self._name}] listen error: {e}")
                time.sleep(1.0)
