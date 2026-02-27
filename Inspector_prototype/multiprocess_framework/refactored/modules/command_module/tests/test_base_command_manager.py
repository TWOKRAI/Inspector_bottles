"""
Тесты для BaseCommandManager.

Проверяет базовый интерфейс командного менеджера.
"""

import unittest
from typing import Dict, Any, Callable, List

from ..core.base_command_manager import BaseCommandManager


class ConcreteCommandManager(BaseCommandManager):
    """Конкретная реализация для тестирования."""
    
    def __init__(self, process_name: str):
        super().__init__(process_name)
        self._commands = {}
    
    def register_command(self, command_name: str, handler: Callable, **kwargs) -> bool:
        self._commands[command_name] = handler
        return True
    
    def handle_command(self, message: Dict) -> Any:
        command_name = message.get("command")
        if command_name in self._commands:
            handler = self._commands[command_name]
            data = message.get("data", {})
            return handler(data)
        return {"status": "error", "reason": "Command not found"}
    
    def get_commands(self) -> List[Dict]:
        return [{"key": name} for name in self._commands.keys()]


class TestBaseCommandManager(unittest.TestCase):
    """Тесты для BaseCommandManager."""
    
    def setUp(self):
        """Подготовка тестового окружения."""
        self.manager = ConcreteCommandManager("test_process")
    
    def test_initialization(self):
        """Тест инициализации базового менеджера."""
        self.assertEqual(self.manager.process_name, "test_process")
    
    def test_register_command(self):
        """Тест регистрации команды."""
        def handler(data):
            return {"result": "ok"}
        
        result = self.manager.register_command("test", handler)
        
        self.assertTrue(result)
        commands = self.manager.get_commands()
        self.assertEqual(len(commands), 1)
    
    def test_handle_command(self):
        """Тест выполнения команды."""
        def handler(data):
            return {"result": data.get("value", 0) * 2}
        
        self.manager.register_command("process", handler)
        
        message = {"command": "process", "data": {"value": 5}}
        result = self.manager.handle_command(message)
        
        self.assertEqual(result["result"], 10)
    
    def test_handle_command_not_found(self):
        """Тест выполнения несуществующей команды."""
        message = {"command": "unknown", "data": {}}
        result = self.manager.handle_command(message)
        
        self.assertEqual(result["status"], "error")
    
    def test_get_commands(self):
        """Тест получения списка команд."""
        def handler1(data):
            return {}
        def handler2(data):
            return {}
        
        self.manager.register_command("cmd1", handler1)
        self.manager.register_command("cmd2", handler2)
        
        commands = self.manager.get_commands()
        self.assertEqual(len(commands), 2)


if __name__ == '__main__':
    unittest.main()

