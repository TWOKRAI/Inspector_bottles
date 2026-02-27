"""
Канал для работы с очередями (Refactored).
"""

from queue import Queue, Empty
import threading
import time
from typing import Dict, Any, List, Callable, Optional

from .base_channel import MessageChannel


class QueueChannel(MessageChannel):
    """
    Канал для работы с очередями.
    
    Поддерживает как стандартные queue.Queue, так и multiprocessing.Queue.
    """
    
    def __init__(self, name: str, queue: Optional[Queue] = None):
        """
        Инициализация канала очереди.
        
        Args:
            name: Имя канала
            queue: Очередь (queue.Queue или multiprocessing.Queue)
        """
        self._name = name
        self._queue = queue or Queue()
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
        """Отправить сообщение в очередь."""
        try:
            self._queue.put(message)
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
    
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Опрос очереди для получения сообщений."""
        messages = []
        
        try:
            if timeout > 0:
                # Блокирующий опрос с таймаутом
                message = self._queue.get(timeout=timeout)
                if message:
                    messages.append(message)
            else:
                # Non-blocking опрос
                while True:
                    try:
                        message = self._queue.get_nowait()
                        if message:
                            messages.append(message)
                    except Empty:
                        break
        except Empty:
            pass
        except Exception as e:
            # Логирование ошибки
            print(f"QueueChannel poll error: {e}")
        
        return messages
    
    def start_listening(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """Запуск асинхронного прослушивания очереди."""
        if self._listening:
            return False
            
        self._callback = callback
        self._listening = True
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            daemon=True
        )
        self._listener_thread.start()
        return True
    
    def _listen_loop(self):
        """Цикл асинхронного прослушивания."""
        while self._listening:
            try:
                messages = self.poll(timeout=0.1)
                for message in messages:
                    if self._callback and message:
                        self._callback(message)
            except Exception as e:
                print(f"QueueChannel listen error: {e}")
                time.sleep(1)
    
    def stop_listening(self) -> bool:
        """Остановить прослушивание."""
        self._listening = False
        if self._listener_thread:
            self._listener_thread.join(timeout=1.0)
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Получить информацию о канале очереди."""
        info = super().get_info()
        
        # Пытаемся получить размер очереди (может не поддерживаться на некоторых платформах)
        try:
            queue_size = self._queue.qsize()
        except (NotImplementedError, OSError, AttributeError):
            queue_size = None
        
        info.update({
            "queue_size": queue_size,
            "listening": self._listening
        })
        return info

