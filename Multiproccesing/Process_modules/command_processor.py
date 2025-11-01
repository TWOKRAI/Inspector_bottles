import queue
import time
import threading
from typing import Dict, List, Any, Optional, Callable, Union
from enum import Enum
import json

class CommandStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"
    EXECUTING = "executing"

class CommandProcessor:
    """
    Независимый менеджер для обработки команд.
    Отвечает только за прием, маршрутизацию и выполнение команд.
    """
    
    def __init__(self, name: str, control_queue: Optional[queue.Queue] = None):
        self.name = name
        self.control_queue = control_queue
        self.is_running = False
        
        # Реестр обработчиков команд
        self.command_handlers: Dict[str, Callable] = {}
        
        # Очередь для внутренних команд
        self.internal_queue = queue.Queue()
        
        # История выполненных команд (для отладки)
        self.command_history: List[Dict] = []
        self.max_history_size = 100
        
        # Таймауты и ограничения
        self.default_timeout = 30.0
        self.max_concurrent_commands = 10
        
        # Текущие выполняющиеся команды
        self.executing_commands: Dict[str, Dict] = {}
        
        # Callback'и для событий
        self.event_callbacks = {
            'command_received': [],
            'command_completed': [],
            'command_failed': [],
            'unknown_command': []
        }
    
    def start(self):
        """Запуск процессора команд"""
        self.is_running = True
        self._log_event("CommandProcessor started")
        
    def stop(self):
        """Остановка процессора команд"""
        self.is_running = False
        self._log_event("CommandProcessor stopping...")
        
        # Ждем завершения текущих команд (с таймаутом)
        start_time = time.time()
        while self.executing_commands and (time.time() - start_time < 5.0):
            time.sleep(0.1)
        
        self._log_event("CommandProcessor stopped")
    
    def register_handler(self, command: str, handler: Callable) -> bool:
        """
        Регистрация обработчика для команды
        
        Args:
            command: Имя команды
            handler: Функция-обработчик (должна принимать данные команды и возвращать результат)
            
        Returns:
            bool: Успешно ли зарегистрирован обработчик
        """
        if command in self.command_handlers:
            self._log_event(f"Handler for command '{command}' already exists", level="WARNING")
            return False
        
        self.command_handlers[command] = handler
        self._log_event(f"Registered handler for command: {command}")
        return True
    
    def unregister_handler(self, command: str) -> bool:
        """Удаление обработчика команды"""
        if command in self.command_handlers:
            del self.command_handlers[command]
            self._log_event(f"Unregistered handler for command: {command}")
            return True
        return False
    
    def process_command(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Синхронная обработка команды
        
        Args:
            command_data: Данные команды (должны содержать 'command')
            
        Returns:
            Dict: Результат выполнения команды
        """
        command_name = command_data.get('command')
        command_id = command_data.get('id', f"cmd_{int(time.time()*1000)}")
        
        if not command_name:
            return self._create_response(command_id, CommandStatus.ERROR, 
                                       error="Missing 'command' field")
        
        self._fire_event('command_received', command_id, command_name, command_data)
        
        # Проверяем существование обработчика
        if command_name not in self.command_handlers:
            self._fire_event('unknown_command', command_id, command_name, command_data)
            return self._create_response(command_id, CommandStatus.ERROR, 
                                       error=f"Unknown command: {command_name}")
        
        # Проверяем лимит concurrent команд
        if len(self.executing_commands) >= self.max_concurrent_commands:
            return self._create_response(command_id, CommandStatus.ERROR,
                                       error="Too many concurrent commands")
        
        # Выполняем команду
        try:
            # Добавляем в выполняющиеся
            self.executing_commands[command_id] = {
                'command': command_name,
                'start_time': time.time(),
                'data': command_data,
                'status': CommandStatus.EXECUTING
            }
            
            # Получаем обработчик
            handler = self.command_handlers[command_name]
            
            # Выполняем команду
            self._log_event(f"Executing command: {command_name} (id: {command_id})")
            result = handler(command_data)
            
            # Удаляем из выполняющихся
            del self.executing_commands[command_id]
            
            # Сохраняем в историю
            self._add_to_history(command_id, command_name, command_data, 
                               CommandStatus.SUCCESS, result)
            
            self._fire_event('command_completed', command_id, command_name, result)
            
            return self._create_response(command_id, CommandStatus.SUCCESS, result=result)
            
        except Exception as e:
            # Удаляем из выполняющихся
            if command_id in self.executing_commands:
                del self.executing_commands[command_id]
            
            error_msg = f"Error executing command {command_name}: {str(e)}"
            self._log_event(error_msg, level="ERROR")
            
            # Сохраняем в историю
            self._add_to_history(command_id, command_name, command_data,
                               CommandStatus.ERROR, None, error_msg)
            
            self._fire_event('command_failed', command_id, command_name, e)
            
            return self._create_response(command_id, CommandStatus.ERROR, error=error_msg)
    
    def process_command_async(self, command_data: Dict[str, Any]) -> str:
        """
        Асинхронная обработка команды
        
        Args:
            command_data: Данные команды
            
        Returns:
            str: ID команды для отслеживания статуса
        """
        command_id = command_data.get('id', f"async_{int(time.time()*1000)}")
        command_data['id'] = command_id
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(
            target=self._async_command_wrapper,
            args=(command_data,),
            daemon=True
        )
        thread.start()
        
        return command_id
    
    def _async_command_wrapper(self, command_data: Dict[str, Any]):
        """Обертка для асинхронного выполнения команды"""
        self.process_command(command_data)
    
    def process_queue(self, timeout: float = 0.1) -> bool:
        """
        Обработка команд из внешней очереди
        
        Args:
            timeout: Таймаут ожидания команды
            
        Returns:
            bool: Была ли обработана хотя бы одна команда
        """
        if not self.control_queue:
            return False
        
        try:
            # Пытаемся получить команду из очереди
            command_data = self.control_queue.get(timeout=timeout)
            
            # Обрабатываем команду
            result = self.process_command(command_data)
            
            # Если в команде указана очередь для ответа, отправляем результат
            response_queue = command_data.get('response_queue')
            if response_queue:
                response_queue.put(result)
            
            return True
            
        except queue.Empty:
            return False
        except Exception as e:
            self._log_event(f"Error processing queue: {e}", level="ERROR")
            return False
    
    def send_internal_command(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправка внутренней команды (внутри процесса)
        
        Args:
            command_data: Данные команды
            
        Returns:
            Dict: Результат выполнения
        """
        self.internal_queue.put(command_data)
        return self.process_command(command_data)
    
    def process_internal_commands(self, timeout: float = 0.1) -> bool:
        """
        Обработка команд из внутренней очереди
        
        Args:
            timeout: Таймаут ожидания команды
            
        Returns:
            bool: Была ли обработана хотя бы одна команда
        """
        try:
            command_data = self.internal_queue.get(timeout=timeout)
            self.process_command(command_data)
            return True
        except queue.Empty:
            return False
    
    def get_command_status(self, command_id: str) -> Optional[Dict[str, Any]]:
        """Получение статуса команды"""
        # Проверяем выполняющиеся команды
        if command_id in self.executing_commands:
            cmd_info = self.executing_commands[command_id]
            return {
                'id': command_id,
                'command': cmd_info['command'],
                'status': cmd_info['status'].value,
                'executing_time': time.time() - cmd_info['start_time'],
                'in_progress': True
            }
        
        # Ищем в истории
        for record in reversed(self.command_history):
            if record['id'] == command_id:
                return {
                    'id': command_id,
                    'command': record['command'],
                    'status': record['status'].value,
                    'executing_time': record.get('execution_time', 0),
                    'in_progress': False,
                    'result': record.get('result'),
                    'error': record.get('error')
                }
        
        return None
    
    def get_recent_commands(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Получение последних команд из истории"""
        return self.command_history[-limit:]
    
    def get_handlers_info(self) -> Dict[str, Any]:
        """Получение информации о зарегистрированных обработчиках"""
        info = {}
        for command, handler in self.command_handlers.items():
            info[command] = {
                'handler': handler.__name__ if hasattr(handler, '__name__') else str(handler),
                'module': handler.__module__ if hasattr(handler, '__module__') else 'unknown'
            }
        return info
    
    def _create_response(self, command_id: str, status: CommandStatus, 
                        result: Any = None, error: str = None) -> Dict[str, Any]:
        """Создание ответа на команду"""
        response = {
            'id': command_id,
            'status': status.value,
            'timestamp': time.time()
        }
        
        if result is not None:
            response['result'] = result
            
        if error is not None:
            response['error'] = error
            
        return response
    
    def _add_to_history(self, command_id: str, command_name: str, 
                       command_data: Dict, status: CommandStatus, 
                       result: Any = None, error: str = None):
        """Добавление команды в историю"""
        record = {
            'id': command_id,
            'command': command_name,
            'data': command_data,
            'status': status,
            'timestamp': time.time(),
            'execution_time': time.time() - command_data.get('_start_time', time.time())
        }
        
        if result is not None:
            record['result'] = result
            
        if error is not None:
            record['error'] = error
        
        self.command_history.append(record)
        
        # Ограничиваем размер истории
        if len(self.command_history) > self.max_history_size:
            self.command_history.pop(0)
    
    # Callback система для событий
    def register_callback(self, event_type: str, callback: Callable):
        """Регистрация callback'а для события"""
        if event_type in self.event_callbacks:
            self.event_callbacks[event_type].append(callback)
    
    def unregister_callback(self, event_type: str, callback: Callable):
        """Удаление callback'а для события"""
        if event_type in self.event_callbacks:
            if callback in self.event_callbacks[event_type]:
                self.event_callbacks[event_type].remove(callback)
    
    def _fire_event(self, event_type: str, *args, **kwargs):
        """Вызов всех callback'ов для события"""
        if event_type in self.event_callbacks:
            for callback in self.event_callbacks[event_type]:
                try:
                    callback(event_type, *args, **kwargs)
                except Exception as e:
                    self._log_event(f"Error in event callback {event_type}: {e}", level="ERROR")
    
    def _log_event(self, message: str, level: str = "INFO"):
        """Логирование событий (для интеграции с LoggerManager)"""
        print(f"[CommandProcessor {level}] {message}")
    
    # Методы для интеграции с ProcessModule
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса менеджера для мониторинга"""
        return {
            'running': self.is_running,
            'registered_handlers': len(self.command_handlers),
            'executing_commands': len(self.executing_commands),
            'command_history_size': len(self.command_history),
            'has_control_queue': self.control_queue is not None,
            'handlers': list(self.command_handlers.keys())
        }
    
    def is_ready(self) -> bool:
        """Проверка готовности менеджера"""
        return self.is_running
    












    # Создание процессора команд
command_processor = CommandProcessor("VideoProcessor")

# Обработчики команд
def handle_start_processing(command_data):
    """Обработчик команды начала обработки"""
    print(f"Starting processing with params: {command_data.get('params')}")
    return {"status": "started", "timestamp": time.time()}

def handle_stop_processing(command_data):
    """Обработчик команды остановки обработки"""
    print("Stopping processing")
    return {"status": "stopped", "timestamp": time.time()}

def handle_get_status(command_data):
    """Обработчик команды получения статуса"""
    return {
        "status": "running",
        "processed_frames": 150,
        "fps": 30.5
    }


if __name__ == "__main__":
    # Регистрация обработчиков
    command_processor.register_handler("start_processing", handle_start_processing)
    command_processor.register_handler("stop_processing", handle_stop_processing)
    command_processor.register_handler("get_status", handle_get_status)

    # Запуск процессора
    command_processor.start()

    # Синхронная обработка команд
    result1 = command_processor.process_command({
        "command": "start_processing",
        "params": {"fps": 30, "resolution": "1080p"},
        "id": "cmd_001"
    })

    result2 = command_processor.process_command({
        "command": "get_status",
        "id": "cmd_002"
    })

    print("Результат команды start_processing:", result1)
    print("Результат команды get_status:", result2)

    # Асинхронная обработка
    async_id = command_processor.process_command_async({
        "command": "stop_processing",
        "id": "async_001"
    })

    # Проверка статуса асинхронной команды
    time.sleep(0.1)
    status = command_processor.get_command_status(async_id)
    print("Статус асинхронной команды:", status)

    # Получение истории команд
    history = command_processor.get_recent_commands(5)
    print("Последние 5 команд:", history)

    # Остановка процессора
    command_processor.stop()