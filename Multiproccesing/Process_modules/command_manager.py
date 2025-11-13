# command_manager.py (обновленная версия)
import queue
import time
import uuid
from typing import Dict, List, Any, Optional, Callable
from dataclasses import asdict
from module_message import CommandMessage, SystemMessage, MessageType, MessageFactory


class CommandManager:
    def __init__(self, process_name: str):
        self.process_name = process_name
        
        # Очереди для SystemMessage
        self.input_queues: Dict[str, queue.Queue] = {}
        self.output_queues: Dict[str, queue.Queue] = {}
        
        # Обработчики команд
        self._handlers: Dict[str, Callable] = {}
        
        # История для отладки
        self._enable_history = False
        self._history: List[Dict] = []
        
        # Колбэки для интеграции
        self.callbacks = {
            'message_received': [],
            'message_processed': [], 
            'message_failed': [],
            'message_sent': []
        }
    
    def register_input_queue(self, name: str, queue_obj: queue.Queue):
        self.input_queues[name] = queue_obj
    
    def register_output_queue(self, name: str, queue_obj: queue.Queue):
        self.output_queues[name] = queue_obj
    
    def register_handler(self, command_type: str, handler: Callable):
        self._handlers[command_type] = handler
    
    def send_message(self, message: SystemMessage, output_queue: str = None) -> str:
        """Универсальная отправка SystemMessage"""
        queue_to_use = None
        if output_queue and output_queue in self.output_queues:
            queue_to_use = self.output_queues[output_queue]
        elif self.output_queues:
            queue_to_use = next(iter(self.output_queues.values()))
        
        if not queue_to_use:
            return message.msg_id
        
        try:
            queue_to_use.put(message.to_dict())
            self._add_to_history(message, "sent")
            self._trigger_callbacks('message_sent', message)
        except Exception as e:
            # Отправляем сообщение об ошибке
            error_msg = MessageFactory.create_log(
                self.process_name, "ERROR", f"Failed to send message: {e}"
            )
            self._trigger_callbacks('message_failed', message, e)
        
        return message.msg_id
    
    # Совместимость со старым API
    def send_command(self, command_type: str, target: Optional[str] = None, data: Any = None, output_queue: Optional[str] = None) -> str:
        """Старый метод для обратной совместимости"""
        message = MessageFactory.create_command(
            self.process_name, command_type, data, target
        )
        return self.send_message(message, output_queue)
    
    def process_loop(self, stop_event, pause_event):
        """Обработка SystemMessage в цикле"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            for queue_name, queue_obj in self.input_queues.items():
                self._process_queue(queue_obj, queue_name)
            time.sleep(0.01)
    
    def _process_queue(self, queue_obj: queue.Queue, queue_name: str):
        """Обработка одной очереди SystemMessage"""
        try:
            message_data = queue_obj.get_nowait()
            message = SystemMessage.from_dict(message_data)
            
            # Обрабатываем только командные сообщения
            if message.msg_type == MessageType.COMMAND:
                self._execute_command_message(message, queue_name)
            else:
                # Пропускаем другие типы сообщений для других менеджеров
                self._trigger_callbacks('message_received', message, queue_name)
                
        except queue.Empty:
            pass
        except Exception as e:
            error_msg = MessageFactory.create_log(
                self.process_name, "ERROR", f"Message processing error: {e}"
            )
            self._trigger_callbacks('message_failed', None, e)
    
    def _execute_command_message(self, message: SystemMessage, source_queue: str):
        """Выполнение команды из SystemMessage"""
        if not isinstance(message, CommandMessage):
            message = CommandMessage(**message.to_dict())
        
        self._add_to_history(message, "received")
        self._trigger_callbacks('message_received', message, source_queue)
        
        # Извлекаем команду из сообщения
        command_name = message.command_name
        handler = self._handlers.get(command_name)
        
        if not handler:
            self._handle_unknown_command(message)
            return
        
        self._add_to_history(message, "processing")
        
        try:
            # Передаем аргументы команды в обработчик
            result = handler(message.command_args)
            self._add_to_history(message, "completed", result=result)
            self._trigger_callbacks('message_processed', message, result)
            
            # Отправляем ответ если нужно
            if message.metadata.get('expect_response'):
                response = message.create_response(result)
                self.send_message(response)
                
        except Exception as e:
            self._add_to_history(message, "failed", error=str(e))
            self._trigger_callbacks('message_failed', message, e)
    
    def _handle_unknown_command(self, message: SystemMessage):
        """Обработка неизвестной команды"""
        self._add_to_history(message, "failed", error="Unknown command")
        self._trigger_callbacks('message_failed', message, Exception("Unknown command"))
    
    def _add_to_history(self, message: SystemMessage, status: str, **kwargs):
        """Добавление в историю"""
        if not self._enable_history:
            return
            
        record = {
            'msg_id': message.msg_id,
            'type': message.msg_type.value,
            'sender': message.sender,
            'target': message.target,
            'status': status,
            'timestamp': time.time()
        }
        record.update(kwargs)
        
        self._history.append(record)
        if len(self._history) > 1000:
            self._history.pop(0)
    
    def _trigger_callbacks(self, event_type: str, *args):
        """Вызов колбэков"""
        for callback in self.callbacks.get(event_type, []):
            try:
                callback(*args)
            except Exception as e:
                # Логируем ошибку в колбэке, но не падаем
                pass

    def _execute_command_message(self, message: SystemMessage, source_queue: str):
        """Выполнение команды из SystemMessage"""
        if message.msg_type != MessageType.COMMAND:
            return
            
        # Извлекаем команду из данных сообщения
        command_data = message.data
        if isinstance(command_data, dict):
            command_name = command_data.get('command')
            if command_name:
                handler = self._handlers.get(command_name)
                if handler:
                    try:
                        result = handler(command_data)
                        self._trigger_callbacks('command_processed', message, result)
                    except Exception as e:
                        self._trigger_callbacks('command_failed', message, e)