import queue
import threading
import time
import uuid
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum

class CommandStatus(Enum):
    RECEIVED = "received"
    PROCESSING = "processing" 
    COMPLETED = "completed"
    FAILED = "failed"
    SENT = "sent"

@dataclass
class Command:
    id: str
    type: str
    sender: str
    target: Optional[str] = None
    data: Any = None
    timestamp: float = None
    response_queue: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.metadata is None:
            self.metadata = {}

class CommandManager:
    """
    менеджер команд - только прием, маршрутизация и отправка.
    Интеграция с другими менеджерами через колбэки.
    """
    
    def __init__(self, process_name: str):
        self.process_name = process_name
        self.is_running = False
        self._thread = None
        
        # Очереди
        self.input_queues: Dict[str, queue.Queue] = {}
        self.output_queues: Dict[str, queue.Queue] = {}
        
        # Обработчики команд
        self._handlers: Dict[str, Callable] = {}
        
        # Минимальная история для отладки (опционально)
        self._enable_history = False
        self._history: List[Dict] = []
        
        # Колбэки для интеграции
        self.callbacks = {
            'command_received': [],
            'command_processed': [],
            'command_failed': [],
            'command_sent': []
        }
    
    def register_input_queue(self, name: str, queue_obj: queue.Queue):
        """Регистрация входной очереди"""
        self.input_queues[name] = queue_obj
    
    def register_output_queue(self, name: str, queue_obj: queue.Queue):
        """Регистрация выходной очереди"""
        self.output_queues[name] = queue_obj
    
    def register_handler(self, command_type: str, handler: Callable):
        """Регистрация обработчика команды"""
        self._handlers[command_type] = handler
    
    def register_handlers(self, handlers: Dict[str, Callable]):
        """Регистрация нескольких обработчиков"""
        self._handlers.update(handlers)
    
    def enable_history(self, enabled: bool = True):
        """Включение/выключение истории команд"""
        self._enable_history = enabled
    
    def start(self):
        """Запуск обработки команд в отдельном потоке"""
        if self.is_running:
            return
            
        self.is_running = True
        self._thread = threading.Thread(
            target=self._process_loop,
            daemon=True,
            name=f"CmdMgr-{self.process_name}"
        )
        self._thread.start()
    
    def stop(self):
        """Остановка менеджера"""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=3.0)
    
    def send_command(self, 
                    command_type: str,
                    target: Optional[str] = None,
                    data: Any = None,
                    output_queue: Optional[str] = None) -> str:
        """
        Отправка команды через указанную выходную очередь
        """
        command = Command(
            id=str(uuid.uuid4()),
            type=command_type,
            sender=self.process_name,
            target=target,
            data=data
        )
        
        # Выбор очереди для отправки
        queue_to_use = None
        if output_queue and output_queue in self.output_queues:
            queue_to_use = self.output_queues[output_queue]
        elif self.output_queues:
            queue_to_use = next(iter(self.output_queues.values()))
        
        if not queue_to_use:
            return command.id
        
        try:
            queue_to_use.put(asdict(command))
            self._add_to_history(command, CommandStatus.SENT)
            self._trigger_callbacks('command_sent', command)
        except Exception as e:
            pass
        
        return command.id
    
    def _process_loop(self):
        """Основной цикл обработки команд"""
        while self.is_running:
            for queue_name, queue_obj in self.input_queues.items():
                self._process_queue(queue_obj, queue_name)
            time.sleep(0.01)  # Небольшая пауза между проверками
    
    def _process_queue(self, queue_obj: queue.Queue, queue_name: str):
        """Обработка одной очереди"""
        try:
            command_data = queue_obj.get_nowait()
            command = self._parse_command(command_data)
            
            if command:
                # Запускаем обработку в отдельном потоке
                threading.Thread(
                    target=self._execute_command,
                    args=(command, queue_name),
                    daemon=True
                ).start()
                
        except queue.Empty:
            pass
    
    def _parse_command(self, data: Any) -> Optional[Command]:
        """Парсинг команды из различных форматов"""
        try:
            if isinstance(data, dict):
                return Command(**data)
            return None
        except:
            return None
    
    def _execute_command(self, command: Command, source_queue: str):
        """Выполнение команды с обработкой ошибок"""
        # Уведомляем о получении команды
        self._add_to_history(command, CommandStatus.RECEIVED)
        self._trigger_callbacks('command_received', command, source_queue)
        
        # Ищем обработчик
        handler = self._handlers.get(command.type)
        if not handler:
            self._handle_unknown_command(command)
            return
        
        # Выполняем команду
        self._add_to_history(command, CommandStatus.PROCESSING)
        
        try:
            result = handler(command.data) if command.data else handler()
            self._add_to_history(command, CommandStatus.COMPLETED, result)
            self._trigger_callbacks('command_processed', command, result)
            
            # Отправляем ответ если требуется
            if command.response_queue:
                self._send_response(command, result)
                
        except Exception as e:
            self._add_to_history(command, CommandStatus.FAILED, error=str(e))
            self._trigger_callbacks('command_failed', command, e)
    
    def _handle_unknown_command(self, command: Command):
        """Обработка неизвестной команды"""
        self._add_to_history(command, CommandStatus.FAILED, error="Unknown command")
        self._trigger_callbacks('command_failed', command, Exception("Unknown command"))
    
    def _send_response(self, original_command: Command, response_data: Any):
        """Отправка ответа на команду"""
        response_command = Command(
            id=str(uuid.uuid4()),
            type=f"response.{original_command.type}",
            sender=self.process_name,
            target=original_command.sender,
            data=response_data,
            metadata={'original_command': original_command.id}
        )
        
        self.send_command(
            command_type=response_command.type,
            target=response_command.target,
            data=response_command.data
        )
    
    def _add_to_history(self, command: Command, status: CommandStatus, **kwargs):
        """Добавление в историю (если включено)"""
        if not self._enable_history:
            return
            
        record = {
            'id': command.id,
            'type': command.type,
            'sender': command.sender,
            'target': command.target,
            'status': status.value,
            'timestamp': time.time()
        }
        record.update(kwargs)
        
        self._history.append(record)
        if len(self._history) > 1000:  # Ограничиваем размер
            self._history.pop(0)
    
    def _trigger_callbacks(self, event_type: str, *args):
        """Вызов колбэков для интеграции с другими менеджерами"""
        for callback in self.callbacks.get(event_type, []):
            try:
                callback(*args)
            except:
                pass
    
    # Методы для мониторинга
    def get_status(self) -> Dict[str, Any]:
        """Базовый статус для HealthManager"""
        return {
            'running': self.is_running,
            'thread_alive': self._thread.is_alive() if self._thread else False,
            'input_queues': len(self.input_queues),
            'output_queues': len(self.output_queues),
            'registered_handlers': len(self._handlers)
        }
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        """История команд для отладки"""
        return self._history[-limit:] if self._enable_history else []