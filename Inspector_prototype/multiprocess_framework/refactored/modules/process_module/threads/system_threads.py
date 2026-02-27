"""
Системные потоки процесса.

Отвечает за инициализацию и управление системными потоками.
"""

import time
from typing import Dict


class SystemThreads:
    """
    Управление системными потоками процесса.
    
    Инкапсулирует логику создания и управления системными потоками.
    """
    
    def __init__(self, process):
        """
        Инициализация управления потоками.
        
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process
        self._message_processor_worker = None
    
    def initialize(self):
        """Инициализация системных потоков."""
        if not self.process.worker_manager:
            return
        
        # Импорт ThreadConfig и ThreadPriority из нового рефакторенного модуля
        from ...worker_module import ThreadConfig, ThreadPriority
        
        # Основной поток обработки сообщений
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self._message_processor_worker = self.process.worker_manager.create_worker(
            "message_processor",
            self._message_processing_loop,
            config,
            auto_start=True
        )
    
    def stop(self):
        """Остановка системных потоков."""
        if self._message_processor_worker and self.process.worker_manager:
            try:
                self.process.worker_manager.stop_worker("message_processor")
            except Exception as e:
                self.process._log_error(f"Error stopping message processor: {e}")
    
    def _message_processing_loop(self, stop_event, pause_event):
        """
        Цикл обработки входящих сообщений.
        
        Args:
            stop_event: Событие остановки
            pause_event: Событие паузы
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            try:
                # Получаем сообщения из очередей через роутер
                if self.process.router_manager:
                    messages = self.process.router_manager.receive(timeout=0.0)
                    
                    for message in messages:
                        self._handle_message(message)
                
                # Небольшая пауза чтобы не загружать CPU
                time.sleep(0.01)
                
            except Exception as e:
                self.process._log_error(f"Message processing error: {e}")
                time.sleep(0.1)
    
    def _handle_message(self, message: Dict):
        """
        Обработка входящего сообщения.
        
        Args:
            message: Сообщение для обработки
        """
        try:
            msg_type = message.get('type')
            
            # Маршрутизуем через router для внутренней обработки
            message['channel'] = 'internal'
            if self.process.router_manager:
                result = self.process.router_manager.send(message)
                
                if result.get('status') == 'error':
                    self.process._log_error(f"Message handling failed: {result.get('reason')}")
                    
        except Exception as e:
            self.process._log_error(f"Message handling error: {e}")

