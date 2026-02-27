"""
Тесты для нового функционала Dispatcher с поддержкой всех стратегий одновременно.
"""
import unittest
from typing import Dict, Any

from multiprocess_framework.modules.Dispatch_module import Dispatcher, DispatchStrategy, ScenarioBuilder


class TestMultiStrategyDispatcher(unittest.TestCase):
    """Тесты для Dispatcher с поддержкой всех стратегий."""
    
    def setUp(self):
        """Подготовка тестового окружения."""
        self.dispatcher = Dispatcher("test_dispatcher")
    
    def test_initialization_all_strategies(self):
        """Тест что все стратегии инициализированы."""
        self.assertIn(DispatchStrategy.EXACT_MATCH, self.dispatcher._strategies)
        self.assertIn(DispatchStrategy.PATTERN_MATCH, self.dispatcher._strategies)
        self.assertIn(DispatchStrategy.FALLBACK_MATCH, self.dispatcher._strategies)
        self.assertIn(DispatchStrategy.CHAIN_MATCH, self.dispatcher._strategies)
    
    def test_register_handler_default_strategy(self):
        """Тест регистрации обработчика в стратегию по умолчанию."""
        def handler(data):
            return "result"
        
        result = self.dispatcher.register_handler("test", handler)
        self.assertTrue(result)
        
        # Проверяем что зарегистрирован в EXACT_MATCH (по умолчанию)
        handler_info = self.dispatcher._find_handler_in_strategy("test", DispatchStrategy.EXACT_MATCH)
        self.assertIsNotNone(handler_info)
    
    def test_register_handler_specific_strategy(self):
        """Тест регистрации обработчика в конкретную стратегию."""
        def handler(data):
            return "result"
        
        result = self.dispatcher.register_handler(
            "test",
            handler,
            strategy=DispatchStrategy.FALLBACK_MATCH,
            efficiency=10
        )
        self.assertTrue(result)
        
        # Проверяем что зарегистрирован в FALLBACK_MATCH
        handler_info = self.dispatcher._find_handler_in_strategy("test", DispatchStrategy.FALLBACK_MATCH)
        self.assertIsNotNone(handler_info)
        self.assertEqual(handler_info.efficiency, 10)
    
    def test_dispatch_with_strategy_field(self):
        """Тест диспетчеризации с указанием стратегии в сообщении."""
        def exact_handler(data):
            return "exact"
        
        def fallback_handler(data):
            return "fallback"
        
        # Регистрируем в разных стратегиях
        self.dispatcher.register_handler("test", exact_handler, strategy=DispatchStrategy.EXACT_MATCH)
        self.dispatcher.register_handler("test", fallback_handler, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=5)
        
        # Используем fallback стратегию через поле в сообщении
        message = {
            "command": "test",
            "strategy": "fallback",
            "data": {}
        }
        
        result = self.dispatcher.dispatch(message)
        self.assertEqual(result, "fallback")
    
    def test_dispatch_default_strategy(self):
        """Тест диспетчеризации со стратегией по умолчанию."""
        def handler(data):
            return "result"
        
        self.dispatcher.register_handler("test", handler)
        
        message = {"command": "test", "data": {}}
        result = self.dispatcher.dispatch(message)
        self.assertEqual(result, "result")
    
    def test_dispatch_scenario_via_key(self):
        """Тест диспетчеризации сценария через ключ."""
        def step1(data):
            return {"step": 1, "value": data.get("value", 0) + 1}
        
        def step2(data):
            return {"step": 2, "value": data.get("value", 0) * 2}
        
        # Создаем сценарий
        self.dispatcher.create_scenario("process", "Test scenario")
        self.dispatcher.add_handler_to_scenario("process", "step1", step1, stage=1)
        self.dispatcher.add_handler_to_scenario("process", "step2", step2, stage=2)
        
        # Выполняем через ключ
        message = {"command": "process", "data": {"value": 5}}
        result = self.dispatcher.dispatch(message)
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scenario"], "process")
        self.assertEqual(len(result["stages"]), 2)
    
    def test_dispatch_scenario_via_field(self):
        """Тест диспетчеризации сценария через поле scenario."""
        def step1(data):
            return {"step": 1}
        
        self.dispatcher.create_scenario("my_scenario", "Test")
        self.dispatcher.add_handler_to_scenario("my_scenario", "step1", step1, stage=1)
        
        # Выполняем через поле scenario
        message = {
            "command": "other",
            "scenario": "my_scenario",
            "data": {}
        }
        
        result = self.dispatcher.dispatch(message)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["scenario"], "my_scenario")
    
    def test_find_handler_across_strategies(self):
        """Тест поиска обработчика по всем стратегиям."""
        def handler(data):
            return "found"
        
        # Регистрируем только в FALLBACK_MATCH
        self.dispatcher.register_handler("test", handler, strategy=DispatchStrategy.FALLBACK_MATCH)
        
        # Поиск должен найти в любой стратегии
        handler_info = self.dispatcher._find_handler("test")
        self.assertIsNotNone(handler_info)
        self.assertEqual(handler_info.handler({}), "found")
    
    def test_scenarios_separate_storage(self):
        """Тест что сценарии хранятся отдельно от обработчиков."""
        def handler(data):
            return "handler"
        
        def step1(data):
            return "step1"
        
        # Регистрируем обработчик
        self.dispatcher.register_handler("test", handler)
        
        # Создаем сценарий с таким же именем
        self.dispatcher.create_scenario("test", "Test scenario")
        self.dispatcher.add_handler_to_scenario("test", "step1", step1, stage=1)
        
        # Оба должны существовать независимо
        handler_info = self.dispatcher._find_handler_in_strategy("test", DispatchStrategy.EXACT_MATCH)
        self.assertIsNotNone(handler_info)
        
        scenario = self.dispatcher.get_scenario_info("test")
        self.assertIsNotNone(scenario)
    
    def test_get_all_handlers_all_strategies(self):
        """Тест получения всех обработчиков из всех стратегий."""
        def handler1(data):
            return "1"
        
        def handler2(data):
            return "2"
        
        def handler3(data):
            return "3"
        
        # Регистрируем в разных стратегиях
        self.dispatcher.register_handler("cmd1", handler1, strategy=DispatchStrategy.EXACT_MATCH)
        self.dispatcher.register_handler("cmd2", handler2, strategy=DispatchStrategy.FALLBACK_MATCH)
        self.dispatcher.register_handler("cmd3", handler3, strategy=DispatchStrategy.PATTERN_MATCH)
        
        all_handlers = self.dispatcher.get_all_handlers()
        handler_keys = [h["key"] for h in all_handlers]
        
        self.assertIn("cmd1", handler_keys)
        self.assertIn("cmd2", handler_keys)
        self.assertIn("cmd3", handler_keys)
    
    def test_get_handlers_by_tag_all_strategies(self):
        """Тест получения обработчиков по тегу из всех стратегий."""
        def handler1(data):
            return "1"
        
        def handler2(data):
            return "2"
        
        # Регистрируем в разных стратегиях с одним тегом
        self.dispatcher.register_handler("cmd1", handler1, tags=["group1"], strategy=DispatchStrategy.EXACT_MATCH)
        self.dispatcher.register_handler("cmd2", handler2, tags=["group1"], strategy=DispatchStrategy.FALLBACK_MATCH)
        
        handlers = self.dispatcher.get_handlers_by_tag("group1")
        self.assertEqual(len(handlers), 2)
        
        handler_keys = [h["key"] for h in handlers]
        self.assertIn("cmd1", handler_keys)
        self.assertIn("cmd2", handler_keys)
    
    def test_pattern_match_strategy(self):
        """Тест работы с PATTERN_MATCH стратегией."""
        def handler(data):
            return "matched"
        
        # Регистрируем паттерн
        self.dispatcher.register_handler(
            r"test_\d+",
            handler,
            strategy=DispatchStrategy.PATTERN_MATCH
        )
        
        # Используем паттерн стратегию
        message = {
            "command": "test_123",
            "strategy": "pattern",
            "data": {}
        }
        
        result = self.dispatcher.dispatch(message)
        self.assertEqual(result, "matched")
    
    def test_fallback_match_strategy(self):
        """Тест работы с FALLBACK_MATCH стратегией."""
        def low_efficiency(data):
            return "low"
        
        def high_efficiency(data):
            return "high"
        
        # Регистрируем несколько обработчиков с разной эффективностью
        self.dispatcher.register_handler(
            "test",
            low_efficiency,
            strategy=DispatchStrategy.FALLBACK_MATCH,
            efficiency=1
        )
        self.dispatcher.register_handler(
            "test",
            high_efficiency,
            strategy=DispatchStrategy.FALLBACK_MATCH,
            efficiency=10
        )
        
        # Используем fallback стратегию
        message = {
            "command": "test",
            "strategy": "fallback",
            "data": {}
        }
        
        result = self.dispatcher.dispatch(message)
        # Должен использоваться обработчик с большей эффективностью
        self.assertEqual(result, "high")


class TestScenarioBuilder(unittest.TestCase):
    """Тесты для ScenarioBuilder."""
    
    def setUp(self):
        """Подготовка тестового окружения."""
        self.dispatcher = Dispatcher("test_dispatcher")
        self.builder = ScenarioBuilder(self.dispatcher)
    
    def test_create_scenario(self):
        """Тест создания сценария."""
        result = self.builder.create("test_scenario", "Test description")
        self.assertTrue(result)
        
        info = self.builder.get_info("test_scenario")
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "test_scenario")
        self.assertEqual(info["description"], "Test description")
    
    def test_add_handler_to_scenario(self):
        """Тест добавления обработчика в сценарий."""
        def handler(data):
            return "result"
        
        self.builder.create("test_scenario")
        result = self.builder.add_handler("test_scenario", "step1", handler, stage=1)
        self.assertTrue(result)
        
        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["handlers_count"], 1)
    
    def test_remove_handler_from_scenario(self):
        """Тест удаления обработчика из сценария."""
        def handler(data):
            return "result"
        
        self.builder.create("test_scenario")
        self.builder.add_handler("test_scenario", "step1", handler, stage=1)
        
        result = self.builder.remove_handler("test_scenario", "step1")
        self.assertTrue(result)
        
        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["handlers_count"], 0)
    
    def test_reorder_handler_in_scenario(self):
        """Тест изменения порядка обработчика в сценарии."""
        def handler1(data):
            return "1"
        
        def handler2(data):
            return "2"
        
        self.builder.create("test_scenario")
        self.builder.add_handler("test_scenario", "step1", handler1, stage=1)
        self.builder.add_handler("test_scenario", "step2", handler2, stage=2)
        
        # Меняем порядок - step2 становится первым (stage=0)
        result = self.builder.reorder("test_scenario", "step2", new_stage=0)
        self.assertTrue(result)
        
        info = self.builder.get_info("test_scenario")
        # step2 должен быть первым (stage=0 < stage=1)
        # Сортируем по stage для проверки
        handlers_sorted = sorted(info["handlers"], key=lambda h: h["stage"])
        self.assertEqual(handlers_sorted[0]["key"], "step2")
        self.assertEqual(handlers_sorted[0]["stage"], 0)
    
    def test_update_metadata(self):
        """Тест обновления метаданных сценария."""
        self.builder.create("test_scenario")
        
        new_metadata = {"version": "2.0", "author": "test"}
        result = self.builder.update_metadata("test_scenario", new_metadata)
        self.assertTrue(result)
        
        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["metadata"]["version"], "2.0")
    
    def test_update_description(self):
        """Тест обновления описания сценария."""
        self.builder.create("test_scenario", "Old description")
        
        result = self.builder.update_description("test_scenario", "New description")
        self.assertTrue(result)
        
        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["description"], "New description")
    
    def test_list_all_scenarios(self):
        """Тест получения списка всех сценариев."""
        self.builder.create("scenario1")
        self.builder.create("scenario2")
        
        scenarios = self.builder.list_all()
        self.assertGreaterEqual(len(scenarios), 2)
        
        scenario_names = [s["name"] for s in scenarios]
        self.assertIn("scenario1", scenario_names)
        self.assertIn("scenario2", scenario_names)
    
    def test_exists(self):
        """Тест проверки существования сценария."""
        self.builder.create("test_scenario")
        
        self.assertTrue(self.builder.exists("test_scenario"))
        self.assertFalse(self.builder.exists("nonexistent"))
    
    def test_delete_scenario(self):
        """Тест удаления сценария."""
        self.builder.create("test_scenario")
        
        result = self.builder.delete("test_scenario")
        self.assertTrue(result)
        
        self.assertFalse(self.builder.exists("test_scenario"))


if __name__ == "__main__":
    unittest.main()

