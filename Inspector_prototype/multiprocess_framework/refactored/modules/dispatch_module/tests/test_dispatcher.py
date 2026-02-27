"""
Тесты для Dispatcher.

Проверяет основную функциональность диспетчера:
- Регистрация обработчиков
- Диспетчеризация сообщений
- Работа со сценариями
- Интеграция с ObservableMixin
"""

import unittest
from typing import Dict, Any

from ..core.dispatcher import Dispatcher
from ..types.types import DispatchStrategy


class TestDispatcher(unittest.TestCase):
    """Тесты для Dispatcher."""
    
    def setUp(self):
        """Подготовка тестового окружения."""
        self.dispatcher = Dispatcher("test_dispatcher")
        self.dispatcher.initialize()
    
    def tearDown(self):
        """Очистка после тестов."""
        if self.dispatcher:
            self.dispatcher.shutdown()
    
    def test_dispatcher_initialization(self):
        """Тест инициализации диспетчера."""
        self.assertEqual(self.dispatcher.manager_name, "test_dispatcher")
        self.assertEqual(self.dispatcher.name, "test_dispatcher")  # Для обратной совместимости
        self.assertEqual(self.dispatcher.strategy, DispatchStrategy.EXACT_MATCH)
        self.assertIsNotNone(self.dispatcher.handlers)
        self.assertTrue(self.dispatcher.is_initialized)
    
    def test_lifecycle_initialize(self):
        """Тест метода initialize()."""
        dispatcher = Dispatcher("lifecycle_test")
        self.assertFalse(dispatcher.is_initialized)
        result = dispatcher.initialize()
        self.assertTrue(result)
        self.assertTrue(dispatcher.is_initialized)
        dispatcher.shutdown()
    
    def test_lifecycle_shutdown(self):
        """Тест метода shutdown()."""
        dispatcher = Dispatcher("lifecycle_test")
        dispatcher.initialize()
        self.assertTrue(dispatcher.is_initialized)
        result = dispatcher.shutdown()
        self.assertTrue(result)
        self.assertFalse(dispatcher.is_initialized)
    
    def test_register_handler_exact_match(self):
        """Тест регистрации обработчика с EXACT_MATCH стратегией."""
        def test_handler(data):
            return {"result": data.get("value", 0) * 2}
        
        result = self.dispatcher.register_handler("process", test_handler)
        
        self.assertTrue(result)
        handler_info = self.dispatcher.get_handler_info("process")
        self.assertIsNotNone(handler_info)
        self.assertEqual(handler_info["key"], "process")
    
    def test_register_handler_pattern_match(self):
        """Тест регистрации обработчика с PATTERN_MATCH стратегией."""
        def pattern_handler(data):
            return {"result": "pattern"}
        
        result = self.dispatcher.register_handler(
            r"pattern_\d+",
            pattern_handler,
            strategy=DispatchStrategy.PATTERN_MATCH
        )
        
        self.assertTrue(result)
    
    def test_register_handler_fallback_match(self):
        """Тест регистрации обработчика с FALLBACK_MATCH стратегией."""
        def fallback_handler(data):
            return {"result": "fallback"}
        
        result = self.dispatcher.register_handler(
            "fallback_cmd",
            fallback_handler,
            strategy=DispatchStrategy.FALLBACK_MATCH,
            efficiency=10
        )
        
        self.assertTrue(result)
    
    def test_dispatch_exact_match(self):
        """Тест диспетчеризации с EXACT_MATCH."""
        def process_handler(data):
            return {"result": data.get("value", 0) * 2}
        
        self.dispatcher.register_handler("process", process_handler)
        
        message = {"command": "process", "data": {"value": 5}}
        result = self.dispatcher.dispatch(message)
        
        self.assertEqual(result["result"], 10)
    
    def test_dispatch_pattern_match(self):
        """Тест диспетчеризации с PATTERN_MATCH."""
        def pattern_handler(data):
            return {"result": "pattern_matched"}
        
        self.dispatcher.register_handler(
            r"process_\d+",
            pattern_handler,
            strategy=DispatchStrategy.PATTERN_MATCH
        )
        
        message = {"command": "process_123", "data": {}}
        result = self.dispatcher.dispatch(message)
        
        self.assertEqual(result["result"], "pattern_matched")
    
    def test_dispatch_fallback_match(self):
        """Тест диспетчеризации с FALLBACK_MATCH."""
        def slow_handler(data):
            return {"result": "slow"}
        
        def fast_handler(data):
            return {"result": "fast"}
        
        # Регистрируем медленный обработчик с низкой эффективностью
        self.dispatcher.register_handler(
            "process",
            slow_handler,
            strategy=DispatchStrategy.FALLBACK_MATCH,
            efficiency=1
        )
        
        # Регистрируем быстрый обработчик с высокой эффективностью
        self.dispatcher.register_handler(
            "process",
            fast_handler,
            strategy=DispatchStrategy.FALLBACK_MATCH,
            efficiency=10
        )
        
        message = {"command": "process", "strategy": "fallback", "data": {}}
        result = self.dispatcher.dispatch(message)
        
        # Должен использоваться быстрый обработчик
        self.assertEqual(result["result"], "fast")
    
    def test_dispatch_handler_not_found(self):
        """Тест диспетчеризации с несуществующим обработчиком."""
        message = {"command": "unknown", "data": {}}
        result = self.dispatcher.dispatch(message)
        
        self.assertEqual(result["status"], "error")
        self.assertIn("No handler", result["reason"])
    
    def test_dispatch_with_full_message(self):
        """Тест диспетчеризации с expects_full_message=True."""
        def full_message_handler(message):
            return {"command": message.get("command"), "full": True}
        
        self.dispatcher.register_handler(
            "full_message",
            full_message_handler,
            expects_full_message=True
        )
        
        message = {"command": "full_message", "data": {"test": "value"}}
        result = self.dispatcher.dispatch(message)
        
        self.assertTrue(result["full"])
        self.assertEqual(result["command"], "full_message")
    
    def test_get_all_handlers(self):
        """Тест получения всех обработчиков."""
        def handler1(data):
            return {}
        def handler2(data):
            return {}
        
        self.dispatcher.register_handler("handler1", handler1)
        self.dispatcher.register_handler("handler2", handler2)
        
        handlers = self.dispatcher.get_all_handlers()
        
        self.assertGreaterEqual(len(handlers), 2)
        handler_keys = [h["key"] for h in handlers]
        self.assertIn("handler1", handler_keys)
        self.assertIn("handler2", handler_keys)
    
    def test_get_handlers_by_tag(self):
        """Тест получения обработчиков по тегу."""
        def vision_handler(data):
            return {}
        
        def audio_handler(data):
            return {}
        
        self.dispatcher.register_handler(
            "vision_process",
            vision_handler,
            tags=["vision", "image"]
        )
        
        self.dispatcher.register_handler(
            "audio_process",
            audio_handler,
            tags=["audio", "sound"]
        )
        
        vision_handlers = self.dispatcher.get_handlers_by_tag("vision")
        
        self.assertEqual(len(vision_handlers), 1)
        self.assertEqual(vision_handlers[0]["key"], "vision_process")
    
    def test_update_handler_metadata(self):
        """Тест обновления метаданных обработчика."""
        def handler(data):
            return {}
        
        self.dispatcher.register_handler(
            "test",
            handler,
            metadata={"version": 1}
        )
        
        result = self.dispatcher.update_handler_metadata(
            "test",
            {"version": 2, "updated": True}
        )
        
        self.assertTrue(result)
        handler_info = self.dispatcher.get_handler_info("test")
        self.assertEqual(handler_info["metadata"]["version"], 2)
        self.assertTrue(handler_info["metadata"]["updated"])
    
    def test_scenario_creation(self):
        """Тест создания сценария."""
        result = self.dispatcher.create_scenario(
            "test_scenario",
            "Тестовый сценарий",
            {"type": "test"}
        )
        
        self.assertTrue(result)
        scenario_info = self.dispatcher.get_scenario_info("test_scenario")
        self.assertIsNotNone(scenario_info)
        self.assertEqual(scenario_info["name"], "test_scenario")
    
    def test_scenario_dispatch(self):
        """Тест выполнения сценария."""
        # Создаем сценарий
        self.dispatcher.create_scenario("image_processing", "Обработка изображений")
        
        # Добавляем обработчики
        def preprocess(data):
            return {"preprocessed": True, "data": data}
        
        def process(data):
            return {"processed": True, "result": data}
        
        self.dispatcher.add_handler_to_scenario(
            "image_processing",
            "preprocess",
            preprocess,
            stage=1
        )
        
        self.dispatcher.add_handler_to_scenario(
            "image_processing",
            "process",
            process,
            stage=2
        )
        
        # Выполняем сценарий
        message = {"command": "image_processing", "data": {"image": "test.jpg"}}
        result = self.dispatcher.dispatch(message)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scenario"], "image_processing")
        self.assertEqual(len(result["stages"]), 2)
        self.assertIsNotNone(result["final_result"])


if __name__ == '__main__':
    unittest.main()

