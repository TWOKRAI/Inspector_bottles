"""
Тесты для типов данных DispatchModule.

Проверяет корректность работы DispatchStrategy, HandlerInfo и Scenario.
"""

import unittest

from ..types.types import DispatchStrategy, HandlerInfo, Scenario


class TestDispatchStrategy(unittest.TestCase):
    """Тесты для DispatchStrategy."""

    def test_strategy_values(self):
        """Проверяем значения стратегий."""
        self.assertEqual(DispatchStrategy.EXACT_MATCH.value, "exact")
        self.assertEqual(DispatchStrategy.PATTERN_MATCH.value, "pattern")
        self.assertEqual(DispatchStrategy.FALLBACK_MATCH.value, "fallback")
        self.assertEqual(DispatchStrategy.CHAIN_MATCH.value, "chain")

    def test_strategy_enum(self):
        """Проверяем, что стратегии являются Enum."""
        self.assertIsInstance(DispatchStrategy.EXACT_MATCH, DispatchStrategy)
        self.assertIsInstance(DispatchStrategy.PATTERN_MATCH, DispatchStrategy)


class TestHandlerInfo(unittest.TestCase):
    """Тесты для HandlerInfo."""

    def test_handler_info_creation(self):
        """Проверяем создание HandlerInfo с параметрами по умолчанию."""

        def test_handler(data):
            return data

        handler_info = HandlerInfo(key="test_handler", handler=test_handler)

        self.assertEqual(handler_info.key, "test_handler")
        self.assertEqual(handler_info.handler, test_handler)
        self.assertFalse(handler_info.expects_full_message)
        self.assertEqual(handler_info.metadata, {})
        self.assertEqual(handler_info.efficiency, 0)
        self.assertEqual(handler_info.tags, set())
        self.assertEqual(handler_info.stage, 0)

    def test_handler_info_with_custom_params(self):
        """Проверяем создание HandlerInfo с кастомными параметрами."""

        def test_handler(data):
            return data

        handler_info = HandlerInfo(
            key="test_handler",
            handler=test_handler,
            expects_full_message=True,
            metadata={"category": "vision", "version": 1},
            efficiency=10,
            tags={"processing", "high_priority"},
            stage=2,
        )

        self.assertEqual(handler_info.key, "test_handler")
        self.assertEqual(handler_info.handler, test_handler)
        self.assertTrue(handler_info.expects_full_message)
        self.assertEqual(handler_info.metadata, {"category": "vision", "version": 1})
        self.assertEqual(handler_info.efficiency, 10)
        self.assertEqual(handler_info.tags, {"processing", "high_priority"})
        self.assertEqual(handler_info.stage, 2)


class TestScenario(unittest.TestCase):
    """Тесты для Scenario."""

    def test_scenario_creation(self):
        """Проверяем создание сценария."""
        scenario = Scenario(name="test_scenario", description="Тестовый сценарий", metadata={"type": "processing"})

        self.assertEqual(scenario.name, "test_scenario")
        self.assertEqual(scenario.description, "Тестовый сценарий")
        self.assertEqual(scenario.metadata, {"type": "processing"})
        self.assertEqual(len(scenario.handlers), 0)

    def test_scenario_add_handler(self):
        """Проверяем добавление обработчика в сценарий."""
        scenario = Scenario(name="test_scenario")

        def handler1(data):
            return data

        handler_info = HandlerInfo(key="handler1", handler=handler1, stage=2)
        result = scenario.add_handler(handler_info, stage=2)

        self.assertTrue(result)
        self.assertEqual(len(scenario.handlers), 1)
        self.assertEqual(scenario.handlers[0].key, "handler1")
        self.assertEqual(scenario.handlers[0].stage, 2)

    def test_scenario_handlers_ordering(self):
        """Проверяем автоматическую сортировку обработчиков по stage."""
        scenario = Scenario(name="test_scenario")

        def handler1(data):
            return data

        def handler2(data):
            return data

        def handler3(data):
            return data

        handler_info1 = HandlerInfo(key="handler1", handler=handler1, stage=3)
        handler_info2 = HandlerInfo(key="handler2", handler=handler2, stage=1)
        handler_info3 = HandlerInfo(key="handler3", handler=handler3, stage=2)

        scenario.add_handler(handler_info1, stage=3)
        scenario.add_handler(handler_info2, stage=1)
        scenario.add_handler(handler_info3, stage=2)

        # Проверяем порядок
        self.assertEqual(scenario.handlers[0].key, "handler2")
        self.assertEqual(scenario.handlers[1].key, "handler3")
        self.assertEqual(scenario.handlers[2].key, "handler1")

    def test_scenario_remove_handler(self):
        """Проверяем удаление обработчика из сценария."""
        scenario = Scenario(name="test_scenario")

        def handler1(data):
            return data

        handler_info = HandlerInfo(key="handler1", handler=handler1, stage=1)
        scenario.add_handler(handler_info, stage=1)

        self.assertEqual(len(scenario.handlers), 1)

        result = scenario.remove_handler("handler1")
        self.assertTrue(result)
        self.assertEqual(len(scenario.handlers), 0)

    def test_scenario_reorder_handler(self):
        """Проверяем изменение порядка обработчика."""
        scenario = Scenario(name="test_scenario")

        def handler1(data):
            return data

        handler_info = HandlerInfo(key="handler1", handler=handler1, stage=1)
        scenario.add_handler(handler_info, stage=1)

        result = scenario.reorder_handler("handler1", new_stage=5)
        self.assertTrue(result)
        self.assertEqual(scenario.handlers[0].stage, 5)

    def test_scenario_get_info(self):
        """Проверяем получение информации о сценарии."""
        scenario = Scenario(name="test_scenario", description="Тестовый сценарий", metadata={"type": "processing"})

        def handler1(data):
            return data

        handler_info = HandlerInfo(key="handler1", handler=handler1, stage=1, metadata={"version": 1}, tags={"test"})
        scenario.add_handler(handler_info, stage=1)

        info = scenario.get_info()

        self.assertEqual(info["name"], "test_scenario")
        self.assertEqual(info["description"], "Тестовый сценарий")
        self.assertEqual(info["metadata"], {"type": "processing"})
        self.assertEqual(info["handlers_count"], 1)
        self.assertEqual(len(info["handlers"]), 1)
        self.assertEqual(info["handlers"][0]["key"], "handler1")


if __name__ == "__main__":
    unittest.main()
