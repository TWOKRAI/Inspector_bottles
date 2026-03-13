"""
Коммуникация процесса — работа с очередями и роутером.

Реализует IProcessCommunication.
Архитектура: ProcessCommunication → RouterManager → Dispatcher → MessageChannel
"""

from queue import Queue as ThreadQueue
from typing import Dict, Any, List, Optional
from multiprocessing import Queue

from ...router_module import QueueChannel
from ..interfaces import IProcessCommunication


class ProcessCommunication(IProcessCommunication):
    """
    Коммуникация процесса.

    Реализует IProcessCommunication.
    Инкапсулирует всю логику работы с очередями и роутером.
    """
    
    def __init__(
        self,
        process_name: str,
        queues: Dict[str, Queue],
        router_manager,
        shared_resources=None,
        logger_callback=None
    ):
        """
        Инициализация коммуникации процесса.
        
        Args:
            process_name: Имя процесса
            queues: Словарь очередей процесса
            router_manager: RouterManager процесса
            shared_resources: SharedResourcesManager (содержит queue_registry)
            logger_callback: Функция для логирования
        """
        self.process_name = process_name
        self.queues = queues or {}
        self.router_manager = router_manager
        self.shared_resources = shared_resources
        self.logger_callback = logger_callback or (lambda level, msg, ctx: print(f"[{level}] {ctx}: {msg}"))
    
    def register_process_queues(self):
        """Регистрация очередей процесса в queue_registry."""
        try:
            # Используем queue_registry из router_manager если доступен
            queue_registry = None
            if self.router_manager and hasattr(self.router_manager, 'queue_registry'):
                queue_registry = self.router_manager.queue_registry
            
            if queue_registry:
                success = queue_registry.register_process_queues(
                    self.process_name, 
                    self.queues
                )
                if success:
                    self.logger_callback("INFO", "Process queues registered in queue_registry", "communication")
                else:
                    self.logger_callback("WARNING", "Failed to register process queues", "communication")
            else:
                self.logger_callback("WARNING", "QueueRegistry not available for registration", "communication")
        except Exception as e:
            self.logger_callback("ERROR", f"Error registering process queues: {e}", "communication")
    
    def register_router_channels(self):
        """Регистрация очередей в роутере через каналы."""
        try:
            if not self.router_manager:
                self.logger_callback("WARNING", "RouterManager not available", "communication")
                return
            
            for queue_name, queue in self.queues.items():
                channel = QueueChannel(f"{self.process_name}_{queue_name}", queue)
                self.router_manager.register_channel(channel)
                self.logger_callback("DEBUG", f"Registered queue channel '{queue_name}' in router", "communication")
            
            # Регистрация каналов для других процессов (из shared_resources) — межпроцессная связь
            if self.shared_resources and self.shared_resources.process_state_registry:
                for target_name in self.shared_resources.process_state_registry.get_process_names():
                    if target_name == self.process_name:
                        continue
                    process_data = self.shared_resources.get_process_data(target_name)
                    if process_data and process_data.queues:
                        for qtype in process_data.queues:
                            queue = process_data.get_queue(qtype)
                            if queue:
                                ch_name = f"{target_name}_{qtype}"
                                if not self.router_manager.get_channel(ch_name):
                                    channel = QueueChannel(ch_name, queue)
                                    self.router_manager.register_channel(channel)
                                    self.logger_callback("DEBUG", f"Registered cross-process channel '{ch_name}'", "communication")
            
            # Локальный канал для межпоточного общения внутри процесса (queue.Queue — быстрый)
            local_channel_name = f"{self.process_name}_local"
            if not self.router_manager.get_channel(local_channel_name):
                local_queue = ThreadQueue(maxsize=256)
                local_channel = QueueChannel(local_channel_name, local_queue)
                self.router_manager.register_channel(local_channel)
                self.logger_callback("DEBUG", f"Registered local intra-process channel '{local_channel_name}'", "communication")

            # Регистрируем канал system_events для событий (если есть очередь events)
            if 'events' in self.queues or self.shared_resources:
                # Создаем или получаем очередь для событий
                events_queue = self.queues.get('events')
                if not events_queue and self.shared_resources:
                    # Пытаемся получить очередь событий из EventManager
                    event_manager = self.shared_resources.event_manager
                    if event_manager:
                        events_queue = event_manager.get_event_queue()
                
                if events_queue:
                    # Регистрируем канал system_events
                    events_channel = QueueChannel("system_events", events_queue)
                    self.router_manager.register_channel(events_channel)
                    self.logger_callback("DEBUG", "Registered system_events channel in router", "communication")
        
        except Exception as e:
            self.logger_callback("ERROR", f"Failed to register queues in router: {e}", "communication")
    
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправить сообщение через роутер.
        
        Args:
            message: Сообщение для отправки
            
        Returns:
            Dict: Результат отправки
        """
        try:
            # Если это объект с методом to_dict (наш BaseMessage)
            if hasattr(message, 'to_dict'):
                message_dict = message.to_dict()
            elif isinstance(message, dict):
                message_dict = message
            else:
                raise TypeError(f"Message must be BaseMessage or dict, got {type(message)}")
            
            if not self.router_manager:
                return {"status": "error", "reason": "RouterManager not available"}
            
            return self.router_manager.send(message_dict)
        except Exception as e:
            self.logger_callback("ERROR", f"Failed to send message: {e}", "communication")
            return {"status": "error", "reason": str(e)}
    
    def receive(self, timeout: float = 0.01) -> List[Dict[str, Any]]:
        """
        Получить входящие сообщения из всех каналов.
        
        Args:
            timeout: Таймаут опроса
            
        Returns:
            List[Dict]: Список полученных сообщений
        """
        try:
            if not self.router_manager:
                return []
            
            return self.router_manager.receive(timeout)
        except Exception as e:
            self.logger_callback("ERROR", f"Failed to receive messages: {e}", "communication")
            return []
    
    def send_to_process(self, target: str, message: Dict[str, Any]) -> bool:
        """
        Отправить сообщение конкретному процессу.
        
        Args:
            target: Имя целевого процесса
            message: Сообщение
            
        Returns:
            bool: True если отправка успешна
        """
        try:
            if not self.router_manager:
                return False
            
            # Используем queue_registry если доступен
            if hasattr(self.router_manager, 'queue_registry') and self.router_manager.queue_registry:
                queue_type = message.get('queue_type', 'system')
                result = self.router_manager.queue_registry.send_to_queue(
                    target, 
                    queue_type, 
                    message
                )
                return result
            
            # Fallback: отправка через роутер
            message['targets'] = [target]
            message['sender'] = self.process_name
            result = self.router_manager.send(message)
            return result.get('status') == 'success'
            
        except Exception as e:
            self.logger_callback("ERROR", f"Failed to send to process '{target}': {e}", "communication")
            return False
    
    def broadcast(self, message: Dict[str, Any], exclude_self: bool = True) -> int:
        """
        Рассылка сообщения всем процессам.
        
        Args:
            message: Сообщение
            exclude_self: Исключить себя из рассылки
            
        Returns:
            int: Количество успешных доставок
        """
        try:
            if not self.router_manager:
                return 0
            
            # Используем queue_registry если доступен
            if hasattr(self.router_manager, 'queue_registry') and self.router_manager.queue_registry:
                exclude_process = self.process_name if exclude_self else None
                queue_type = message.get('queue_type', 'system')
                return self.router_manager.queue_registry.broadcast_message(
                    message, 
                    queue_type, 
                    exclude_process
                )
            
            # Fallback: отправка через роутер с broadcast флагом
            message['targets'] = ['all']
            result = self.router_manager.send(message)
            return 1 if result.get('status') == 'success' else 0
            
        except Exception as e:
            self.logger_callback("ERROR", f"Failed to broadcast message: {e}", "communication")
            return 0
    
    def unregister_process(self):
        """Отменить регистрацию процесса из queue_registry."""
        try:
            # Получаем queue_registry из router_manager если доступен
            if self.router_manager and hasattr(self.router_manager, 'queue_registry'):
                queue_registry = self.router_manager.queue_registry
                if queue_registry:
                    queue_registry.unregister_process(self.process_name)
        except Exception as e:
            self.logger_callback("WARNING", f"Error unregistering process: {e}", "communication")
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Получение статистики очередей."""
        stats = {}
        for name, queue in self.queues.items():
            try:
                try:
                    size = queue.qsize()
                except (NotImplementedError, OSError, AttributeError):
                    size = 0

                maxsize = getattr(queue, "maxsize", None)
                stats[name] = {"size": size, "maxsize": maxsize}
            except Exception as e:
                stats[name] = {"error": str(e) or "Unknown error"}
        return stats

    # ---- Алиасы для IProcessCommunication ----

    def send_message(self, target: str, message: Dict[str, Any]) -> bool:
        """Отправить сообщение конкретному процессу (алиас send_to_process)."""
        return self.send_to_process(target, message)

    def broadcast_message(self, message: Dict[str, Any], exclude_self: bool = True) -> bool:
        """Разослать сообщение всем процессам (алиас broadcast, возвращает bool)."""
        return self.broadcast(message, exclude_self) > 0

    def receive_message(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Получить одно сообщение из очереди."""
        messages = self.receive(timeout=timeout if timeout is not None else 0.01)
        return messages[0] if messages else None

