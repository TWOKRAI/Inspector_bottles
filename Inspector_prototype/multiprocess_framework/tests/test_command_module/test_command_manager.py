"""
Тесты для CommandManager и BaseCommandManager.
"""
import unittest
from typing import Dict, Any

from multiprocess_framework.modules.Command_module import CommandManager, BaseCommandManager
from multiprocess_framework.modules.Dispatch_module import DispatchStrategy


class TestBaseCommandManager(unittest.TestCase):
    """Тесты для BaseCommandManager."""
    
    def test_base_class_is_abstract(self):
        """Проверка что BaseCommandManager является абстрактным классом."""
        # Попытка создать экземпляр должна вызвать ошибку
        with self.assertRaises(TypeError):
            BaseCommandManager("test_process")


class TestCommandManager(unittest.TestCase):
    """Тесты для CommandManager."""
    
    def setUp(self):
        """Подготовка тестового окружения."""
        self.manager = CommandManager("test_process")
    
    def test_initialization(self):
        """Тест инициализации CommandManager."""
        self.assertEqual(self.manager.process_name, "test_process")
        self.assertIsNotNone(self.manager.dispatcher)
        self.assertEqual(self.manager.dispatcher.name, "test_process_commands")
    
    def test_initialization_with_strategy(self):
        """Тест инициализации с указанием стратегии."""
        manager = CommandManager("test", DispatchStrategy.FALLBACK_MATCH)
        self.assertEqual(manager.dispatcher._default_strategy, DispatchStrategy.FALLBACK_MATCH)
    
    def test_register_command(self):
        """Тест регистрации команды."""
        def handler(data):
            return {"result": "success"}
        
        result = self.manager.register_command("test_command", handler)
        self.assertTrue(result)
        
        # Проверка что команда зарегистрирована
        commands = self.manager.get_commands()
        command_names = [cmd["key"] for cmd in commands]
        self.assertIn("test_command", command_names)
    
    def test_register_command_with_metadata(self):
        """Тест регистрации команды с метаданными."""
        def handler(data):
            return {"result": "success"}
        
        metadata = {"description": "Test command", "version": "1.0"}
        result = self.manager.register_command(
            "test_command",
            handler,
            metadata=metadata
        )
        self.assertTrue(result)
        
        # Проверка метаданных
        info = self.manager.get_command_info("test_command")
        self.assertIsNotNone(info)
        self.assertEqual(info["metadata"]["description"], "Test command")
    
    def test_register_command_with_tags(self):
        """Тест регистрации команды с тегами."""
        def handler(data):
            return {"result": "success"}
        
        result = self.manager.register_command(
            "test_command",
            handler,
            tags=["test", "example"]
        )
        self.assertTrue(result)
        
        # Проверка тегов
        commands = self.manager.get_commands_by_tag("test")
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["key"], "test_command")
    
    def test_handle_command(self):
        """Тест обработки команды."""
        def greet_handler(data):
            name = data.get("name", "World")
            return f"Hello, {name}!"
        
        self.manager.register_command("greet", greet_handler)
        
        message = {
            "command": "greet",
            "data": {"name": "Alice"}
        }
        
        result = self.manager.handle_command(message)
        self.assertEqual(result, "Hello, Alice!")
    
    def test_handle_command_not_found(self):
        """Тест обработки несуществующей команды."""
        message = {
            "command": "unknown_command",
            "data": {}
        }
        
        result = self.manager.handle_command(message)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "error")
        self.assertIn("No handler", result["reason"])
    
    def test_handle_command_with_strategy(self):
        """Тест обработки команды с указанием стратегии в сообщении."""
        def handler1(data):
            return "handler1"
        
        def handler2(data):
            return "handler2"
        
        # Регистрируем в разных стратегиях
        self.manager.register_command("test", handler1, strategy=DispatchStrategy.EXACT_MATCH)
        self.manager.register_command("test", handler2, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=10)
        
        # Используем fallback стратегию
        message = {
            "command": "test",
            "strategy": "fallback",
            "data": {}
        }
        
        result = self.manager.handle_command(message)
        self.assertEqual(result, "handler2")
    
    def test_get_commands(self):
        """Тест получения списка команд."""
        def handler1(data):
            return "result1"
        
        def handler2(data):
            return "result2"
        
        self.manager.register_command("command1", handler1)
        self.manager.register_command("command2", handler2)
        
        commands = self.manager.get_commands()
        self.assertGreaterEqual(len(commands), 2)
        
        command_names = [cmd["key"] for cmd in commands]
        self.assertIn("command1", command_names)
        self.assertIn("command2", command_names)
    
    def test_get_command_info(self):
        """Тест получения информации о команде."""
        def handler(data):
            return "result"
        
        metadata = {"description": "Test"}
        self.manager.register_command("test", handler, metadata=metadata)
        
        info = self.manager.get_command_info("test")
        self.assertIsNotNone(info)
        self.assertEqual(info["key"], "test")
        self.assertEqual(info["metadata"]["description"], "Test")
    
    def test_get_command_info_not_found(self):
        """Тест получения информации о несуществующей команде."""
        info = self.manager.get_command_info("nonexistent")
        self.assertIsNone(info)
    
    def test_get_commands_by_tag(self):
        """Тест получения команд по тегу."""
        def handler1(data):
            return "result1"
        
        def handler2(data):
            return "result2"
        
        def handler3(data):
            return "result3"
        
        self.manager.register_command("cmd1", handler1, tags=["group1"])
        self.manager.register_command("cmd2", handler2, tags=["group1", "group2"])
        self.manager.register_command("cmd3", handler3, tags=["group2"])
        
        group1_commands = self.manager.get_commands_by_tag("group1")
        self.assertEqual(len(group1_commands), 2)
        
        group2_commands = self.manager.get_commands_by_tag("group2")
        self.assertEqual(len(group2_commands), 2)
    
    def test_update_command_metadata(self):
        """Тест обновления метаданных команды."""
        def handler(data):
            return "result"
        
        self.manager.register_command("test", handler, metadata={"old": "value"})
        
        new_metadata = {"new": "value", "description": "Updated"}
        result = self.manager.update_command_metadata("test", new_metadata)
        self.assertTrue(result)
        
        info = self.manager.get_command_info("test")
        self.assertEqual(info["metadata"]["new"], "value")
        self.assertEqual(info["metadata"]["description"], "Updated")
    
    def test_update_command_tags(self):
        """Тест обновления тегов команды."""
        def handler(data):
            return "result"
        
        self.manager.register_command("test", handler, tags=["tag1"])
        
        result = self.manager.update_command_tags("test", ["tag2", "tag3"])
        self.assertTrue(result)
        
        commands = self.manager.get_commands_by_tag("tag2")
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["key"], "test")
    
    def test_overwrite_command(self):
        """Тест перезаписи команды."""
        def old_handler(data):
            return "old"
        
        def new_handler(data):
            return "new"
        
        self.manager.register_command("test", old_handler)
        
        # Перезаписываем
        result = self.manager.overwrite_command("test", new_handler)
        self.assertTrue(result)
        
        # Проверяем что используется новый обработчик
        message = {"command": "test", "data": {}}
        response = self.manager.handle_command(message)
        self.assertEqual(response, "new")
    
    def test_handle_command_with_scenario(self):
        """Тест обработки команды через сценарий."""
        def step1(data):
            # Получаем значение и возвращаем словарь с результатом
            value = data.get("value", 0) if isinstance(data, dict) else data
            return {"step": 1, "value": value + 1}
        
        def step2(data):
            # Получаем значение из предыдущего шага
            value = data.get("value", 0) if isinstance(data, dict) else data
            return {"step": 2, "value": value * 2}
        
        # Создаем сценарий
        self.manager.dispatcher.create_scenario("process", "Test scenario")
        self.manager.dispatcher.add_handler_to_scenario("process", "step1", step1, stage=1)
        self.manager.dispatcher.add_handler_to_scenario("process", "step2", step2, stage=2)
        
        # Выполняем сценарий через команду
        message = {
            "command": "process",
            "data": {"value": 5}
        }
        
        result = self.manager.handle_command(message)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scenario"], "process")
        self.assertEqual(len(result["stages"]), 2)
        
        # Проверяем результаты этапов
        self.assertEqual(result["stages"][0]["status"], "success")
        self.assertEqual(result["stages"][1]["status"], "success")
        self.assertEqual(result["stages"][1]["result"]["value"], 12)  # (5+1)*2
    
    def test_multiple_strategies_same_key(self):
        """Тест работы с несколькими стратегиями для одного ключа."""
        def exact_handler(data):
            return "exact"
        
        def fallback_handler(data):
            return "fallback"
        
        # Регистрируем в разных стратегиях
        self.manager.register_command("test", exact_handler, strategy=DispatchStrategy.EXACT_MATCH)
        self.manager.register_command("test", fallback_handler, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=5)
        
        # По умолчанию используется EXACT_MATCH
        message = {"command": "test", "data": {}}
        result = self.manager.handle_command(message)
        self.assertEqual(result, "exact")
        
        # Явно указываем fallback
        message["strategy"] = "fallback"
        result = self.manager.handle_command(message)
        self.assertEqual(result, "fallback")


if __name__ == "__main__":
    unittest.main()

