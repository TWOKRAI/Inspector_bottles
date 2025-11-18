# command_manager.py (обновленная версия с интеграцией роутера)
from typing import Dict, List, Any, Optional, Callable


class CommandManager:
    def __init__(self, process_name: str):
        self.process_name = process_name
        self._handlers: Dict[str, Callable] = {}
    
    def register_handler(self, command_type: str, handler: Callable):
        self._handlers[command_type] = handler
    
    def handle_message(self, message: Dict):
        """Обработка входящего сообщения от роутера"""
        if message.get('type') != 'command':
            return
        
        command_data = message.get('data', {})
        command_name = command_data.get('command')
        
        if command_name and command_name in self._handlers:
            try:
                result = self._handlers[command_name](command_data.get('args', {}))
                # Обработка результата если нужно
            except Exception as e:
                # Ошибки логируются через роутер
                print(f"Command handler error: {e}")