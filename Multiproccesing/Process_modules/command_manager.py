# command_manager.py (обновленная версия с интеграцией роутера)
import queue
import time
import uuid
from typing import Dict, List, Any, Optional, Callable
from module_message import CommandMessage, SystemMessage, MessageType, MessageFactory

class CommandManager:
    def __init__(self, process_name: str):
        self.process_name = process_name
        self._handlers: Dict[str, Callable] = {}
        self.router = None  # Будет установлен из ProcessModule
        
    def set_router(self, router):
        """Установка роутера для отправки сообщений"""
        self.router = router
    
    def register_handler(self, command_type: str, handler: Callable):
        self._handlers[command_type] = handler
    
    def handle_message(self, message: Dict):
        """Обработка входящего сообщения от роутера"""
        if message.get('type') != 'command':
            return
        
        # Преобразуем в CommandMessage для совместимости
        command_msg = CommandMessage.from_dict(message)
        self._execute_command_message(command_msg, "router")
    
    def _execute_command_message(self, message: SystemMessage, source_queue: str):
        """Выполнение команды из SystemMessage"""
        if message.msg_type != MessageType.COMMAND:
            return
            
        command_data = message.data
        if isinstance(command_data, dict):
            command_name = command_data.get('command')
            if command_name:
                handler = self._handlers.get(command_name)
                if handler:
                    try:
                        result = handler(command_data.get('args', {}))
                        # Отправляем ответ если нужно
                        if message.metadata.get('expect_response'):
                            response = message.create_response(result)
                            if self.router:
                                self.router.route_message(response.to_dict())
                    except Exception as e:
                        print(f"Command handler error: {e}")
    
    def send_command(self, command: str, args: Dict, targets: List[str], need_ack: bool = False) -> Dict:
        """Удобный метод отправки команды через роутер"""
        if not self.router:
            return {'status': 'failed', 'error': 'Router not available'}
        
        message = {
            "id": f"cmd_{uuid.uuid4().hex[:8]}",
            "type": "command",
            "sender": self.process_name,
            "targets": targets,
            "routers": [],  # по умолчанию внутренний
            "priority": "normal",
            "need_ack": need_ack,
            "data": {
                "command": command,
                "args": args
            },
            "timestamp": time.time()
        }
        
        return self.router.route_message(message)
    
    # Совместимость со старым API
    def send_message(self, message: SystemMessage, output_queue: str = None) -> str:
        """Старый метод для обратной совместимости"""
        if self.router:
            result = self.router.route_message(message.to_dict())
            return message.msg_id if result.get('status') == 'delivered' else ''
        return ''