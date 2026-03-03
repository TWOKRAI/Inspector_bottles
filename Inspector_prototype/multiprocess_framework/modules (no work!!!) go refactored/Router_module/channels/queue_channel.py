# -*- coding: utf-8 -*-
"""
Канал-обёртка над очередью (multiprocessing.Queue или queue.Queue).
Реализует MessageChannel для использования в RouterManager.
Часть multiprocess_framework — при переносе app в фреймворк остаётся здесь.
"""
from typing import Dict, Any, List, Optional, Callable

try:
    from multiprocessing.queues import Empty
except ImportError:
    from queue import Empty

from ..channel import MessageChannel


class QueueChannel(MessageChannel):
    """
    Канал для работы с одной очередью (MessageChannel интерфейс).
    Поддерживает multiprocessing.Queue и queue.Queue.
    """

    def __init__(self, name: str, queue: Any, event: Any = None):
        """
        Args:
            name: Уникальное имя канала (для регистрации в RouterManager).
            queue: Очередь с интерфейсом put(), get_nowait(), get(timeout=), full(), qsize().
            event: Опционально — объект с методом set() (например multiprocessing.Event).
                   После успешной отправки в очередь вызывается event.set() для пробуждения процесса.
        """
        self._name = name
        self._queue = queue
        self._event = event
        self._listening = False
        self._listener_thread = None
        self._callback = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "queue"

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except Empty:
                    pass
            # Для совместимости с процессами, ожидающими полный словарь управляющих данных:
            # если в сообщении есть 'snapshot', в очередь кладём только его
            payload = message.get("snapshot") if isinstance(message, dict) else message
            if payload is None:
                payload = message
            self._queue.put(payload)
            if self._event is not None and hasattr(self._event, "set"):
                self._event.set()
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        messages = []
        try:
            if timeout > 0:
                msg = self._queue.get(timeout=timeout)
                if msg is not None:
                    messages.append(msg if isinstance(msg, dict) else {"data": msg})
            else:
                while True:
                    try:
                        msg = self._queue.get_nowait()
                        if msg is not None:
                            messages.append(msg if isinstance(msg, dict) else {"data": msg})
                    except Empty:
                        break
        except Empty:
            pass
        except Exception as e:
            if callable(getattr(self._queue, "qsize", None)):
                pass  # ignore in clean shutdown
            else:
                raise e
        return messages

    def start_listening(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        if self._listening:
            return False
        import threading
        import time
        self._callback = callback
        self._listening = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()
        return True

    def _listen_loop(self) -> None:
        import time
        while self._listening:
            try:
                for msg in self.poll(timeout=0.1):
                    if self._callback and msg:
                        self._callback(msg)
            except Exception:
                pass
            time.sleep(0.01)

    def stop_listening(self) -> bool:
        self._listening = False
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=1.0)
            self._listener_thread = None
        return True

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        try:
            info["queue_size"] = self._queue.qsize()
        except (NotImplementedError, OSError, AttributeError):
            info["queue_size"] = 0
        info["listening"] = self._listening
        return info
