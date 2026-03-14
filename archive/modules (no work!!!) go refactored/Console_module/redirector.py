"""
Перенаправитель stdout/stderr в консоль.

Поддерживает множественные получатели (дублирование в несколько консолей).
"""

import sys
import queue
from multiprocessing import Queue
from typing import Optional, List, Union


class ConsoleRedirector:
    """
    Перенаправитель вывода процесса в консоль(и).
    
    Поддерживает дублирование вывода в несколько консолей одновременно.
    """
    
    def __init__(self, output_queues: Union[Queue, List[Queue]], process_name: str):
        """
        Args:
            output_queues: Один Queue или список Queue для отправки данных
            process_name: Имя процесса для префикса
        """
        # Нормализуем в список
        if isinstance(output_queues, Queue):
            self.output_queues = [output_queues]
        else:
            self.output_queues = list(output_queues) if output_queues else []
        
        self.process_name = process_name
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self._closed = False
    
    def write(self, data: str):
        """Запись во все queues с префиксом имени процесса"""
        if self._closed or not data:
            return
        
        try:
            if isinstance(data, bytes):
                data = data.decode('utf-8', errors='replace')
            
            prefixed_data = f"[{self.process_name}] {data}"
            
            # Дублируем во все queues
            for output_queue in self.output_queues:
                try:
                    output_queue.put(('stdout', prefixed_data), block=False)
                except queue.Full:
                    # Игнорируем полные очереди
                    pass
                except Exception:
                    # Игнорируем ошибки отдельных очередей
                    continue
        except Exception:
            self._closed = True
    
    def flush(self):
        """Сброс буфера во все очереди"""
        if self._closed:
            return
        
        for output_queue in self.output_queues:
            try:
                output_queue.put(('flush', ''), block=False)
            except Exception:
                continue
    
    def close(self):
        """Закрытие перенаправителя"""
        self._closed = True
        for output_queue in self.output_queues:
            try:
                output_queue.put(('close', ''), block=False)
            except Exception:
                pass


