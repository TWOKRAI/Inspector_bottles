"""
Тесты для стратегий диспетчеризации.

Проверяет корректность работы всех стратегий.
"""

import unittest

from ..strategies.exact_match import ExactMatchStrategy
from ..strategies.pattern_match import PatternMatchStrategy
from ..strategies.fallback_match import FallbackMatchStrategy
from ..strategies.chain_match import ChainMatchStrategy


class TestExactMatchStrategy(unittest.TestCase):
    """Тесты для ExactMatchStrategy."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.strategy = ExactMatchStrategy("test_dispatcher")
        self.storage = {}

    def test_register_handler(self):
        """Тест регистрации обработчика."""

        def handler(data):
            return data

        result = self.strategy.register_handler("test_key", handler, handlers_storage=self.storage)

        self.assertTrue(result)
        self.assertIn("test_key", self.storage)

    def test_register_duplicate_handler(self):
        """Тест регистрации дубликата обработчика."""

        def handler(data):
            return data

        self.strategy.register_handler("test_key", handler, handlers_storage=self.storage)

        # Попытка зарегистрировать снова
        result = self.strategy.register_handler("test_key", handler, handlers_storage=self.storage)

        self.assertFalse(result)

    def test_find_handler(self):
        """Тест поиска обработчика."""

        def handler(data):
            return data

        self.strategy.register_handler("test_key", handler, handlers_storage=self.storage)

        found = self.strategy.find_handler("test_key", self.storage)

        self.assertIsNotNone(found)
        self.assertEqual(found.key, "test_key")

    def test_find_nonexistent_handler(self):
        """Тест поиска несуществующего обработчика."""
        found = self.strategy.find_handler("nonexistent", self.storage)
        self.assertIsNone(found)


class TestPatternMatchStrategy(unittest.TestCase):
    """Тесты для PatternMatchStrategy."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.strategy = PatternMatchStrategy("test_dispatcher")
        self.storage = []

    def test_register_handler(self):
        """Тест регистрации обработчика с паттерном."""

        def handler(data):
            return data

        result = self.strategy.register_handler(r"pattern_\d+", handler, handlers_storage=self.storage)

        self.assertTrue(result)
        self.assertEqual(len(self.storage), 1)

    def test_register_invalid_pattern(self):
        """Тест регистрации с невалидным паттерном."""

        def handler(data):
            return data

        result = self.strategy.register_handler("[invalid", handler, handlers_storage=self.storage)

        self.assertFalse(result)

    def test_find_handler(self):
        """Тест поиска обработчика по паттерну."""

        def handler(data):
            return data

        self.strategy.register_handler(r"process_\d+", handler, handlers_storage=self.storage)

        found = self.strategy.find_handler("process_123", self.storage)

        self.assertIsNotNone(found)
        self.assertEqual(found.key, r"process_\d+")


class TestFallbackMatchStrategy(unittest.TestCase):
    """Тесты для FallbackMatchStrategy."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.strategy = FallbackMatchStrategy("test_dispatcher")
        self.storage = {}

    def test_register_multiple_handlers(self):
        """Тест регистрации нескольких обработчиков с одним ключом."""

        def handler1(data):
            return "handler1"

        def handler2(data):
            return "handler2"

        result1 = self.strategy.register_handler("process", handler1, efficiency=1, handlers_storage=self.storage)

        result2 = self.strategy.register_handler("process", handler2, efficiency=10, handlers_storage=self.storage)

        self.assertTrue(result1)
        self.assertTrue(result2)
        self.assertEqual(len(self.storage["process"]), 2)

    def test_find_handler_by_efficiency(self):
        """Тест поиска обработчика с наивысшей эффективностью."""

        def handler1(data):
            return "low"

        def handler2(data):
            return "high"

        self.strategy.register_handler("process", handler1, efficiency=1, handlers_storage=self.storage)

        self.strategy.register_handler("process", handler2, efficiency=10, handlers_storage=self.storage)

        found = self.strategy.find_handler("process", self.storage)

        self.assertIsNotNone(found)
        self.assertEqual(found.efficiency, 10)


class TestChainMatchStrategy(unittest.TestCase):
    """Тесты для ChainMatchStrategy."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.strategy = ChainMatchStrategy("test_dispatcher")

    def test_create_scenario(self):
        """Тест создания сценария."""
        result = self.strategy.create_scenario("test_scenario", "Тестовый сценарий")

        self.assertTrue(result)
        self.assertIn("test_scenario", self.strategy.scenarios)

    def test_add_handler_to_scenario(self):
        """Тест добавления обработчика в сценарий."""
        self.strategy.create_scenario("test_scenario")

        def handler(data):
            return data

        result = self.strategy.add_handler_to_scenario("test_scenario", "handler1", handler, stage=1)

        self.assertTrue(result)
        scenario = self.strategy.scenarios["test_scenario"]
        self.assertEqual(len(scenario.handlers), 1)

    def test_dispatch_scenario(self):
        """Тест выполнения сценария."""
        self.strategy.create_scenario("test_scenario")

        def step1(data):
            return {"step": 1, "data": data}

        def step2(data):
            return {"step": 2, "value": data.get("value", 0) + 1}

        self.strategy.add_handler_to_scenario("test_scenario", "step1", step1, stage=1)
        self.strategy.add_handler_to_scenario("test_scenario", "step2", step2, stage=2)

        message = {"data": {"value": 5}}
        result = self.strategy.dispatch_scenario("test_scenario", message)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["stages"]), 2)
        self.assertIsNotNone(result["final_result"])


if __name__ == "__main__":
    unittest.main()
