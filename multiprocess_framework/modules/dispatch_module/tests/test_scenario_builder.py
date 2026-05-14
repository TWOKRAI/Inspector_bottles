"""
Тесты для ScenarioBuilder.

Проверяет корректность работы построителя сценариев.
"""

import unittest

from ..core.dispatcher import Dispatcher
from ..builders.scenario_builder import ScenarioBuilder


class TestScenarioBuilder(unittest.TestCase):
    """Тесты для ScenarioBuilder."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.dispatcher = Dispatcher("test_dispatcher")
        self.builder = ScenarioBuilder(self.dispatcher)

    def test_create_scenario(self):
        """Тест создания сценария через builder."""
        result = self.builder.create("test_scenario", "Тестовый сценарий", {"type": "test"})

        self.assertTrue(result)
        self.assertTrue(self.builder.exists("test_scenario"))

    def test_create_duplicate_scenario(self):
        """Тест создания дубликата сценария."""
        self.builder.create("test_scenario")

        # Попытка создать снова
        result = self.builder.create("test_scenario")

        self.assertFalse(result)

    def test_add_handler(self):
        """Тест добавления обработчика в сценарий."""
        self.builder.create("test_scenario")

        def handler(data):
            return data

        result = self.builder.add_handler("test_scenario", "handler1", handler, stage=1)

        self.assertTrue(result)

        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["handlers_count"], 1)

    def test_remove_handler(self):
        """Тест удаления обработчика из сценария."""
        self.builder.create("test_scenario")

        def handler(data):
            return data

        self.builder.add_handler("test_scenario", "handler1", handler, stage=1)

        result = self.builder.remove_handler("test_scenario", "handler1")

        self.assertTrue(result)

        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["handlers_count"], 0)

    def test_reorder_handler(self):
        """Тест изменения порядка обработчика."""
        self.builder.create("test_scenario")

        def handler1(data):
            return data

        def handler2(data):
            return data

        self.builder.add_handler("test_scenario", "handler1", handler1, stage=1)
        self.builder.add_handler("test_scenario", "handler2", handler2, stage=2)

        # Проверяем начальный порядок
        info_before = self.builder.get_info("test_scenario")
        handlers_before = info_before["handlers"]
        self.assertEqual(handlers_before[0]["key"], "handler1")
        self.assertEqual(handlers_before[1]["key"], "handler2")

        # Меняем порядок: handler2 на stage=0 (раньше handler1)
        result = self.builder.reorder("test_scenario", "handler2", new_stage=0)

        self.assertTrue(result)

        info_after = self.builder.get_info("test_scenario")
        handlers_after = info_after["handlers"]
        # handler2 должен быть первым после изменения порядка (stage=0 < stage=1)
        self.assertEqual(handlers_after[0]["key"], "handler2")
        self.assertEqual(handlers_after[1]["key"], "handler1")

    def test_update_metadata(self):
        """Тест обновления метаданных сценария."""
        self.builder.create("test_scenario", metadata={"version": 1})

        result = self.builder.update_metadata("test_scenario", {"version": 2, "updated": True})

        self.assertTrue(result)

        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["metadata"]["version"], 2)
        self.assertTrue(info["metadata"]["updated"])

    def test_update_description(self):
        """Тест обновления описания сценария."""
        self.builder.create("test_scenario", description="Старое описание")

        result = self.builder.update_description("test_scenario", "Новое описание")

        self.assertTrue(result)

        info = self.builder.get_info("test_scenario")
        self.assertEqual(info["description"], "Новое описание")

    def test_get_info(self):
        """Тест получения информации о сценарии."""
        self.builder.create("test_scenario", "Тестовый сценарий", {"type": "test"})

        info = self.builder.get_info("test_scenario")

        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "test_scenario")
        self.assertEqual(info["description"], "Тестовый сценарий")
        self.assertEqual(info["metadata"], {"type": "test"})

    def test_list_all(self):
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

    def test_delete(self):
        """Тест удаления сценария."""
        self.builder.create("test_scenario")

        self.assertTrue(self.builder.exists("test_scenario"))

        result = self.builder.delete("test_scenario")

        self.assertTrue(result)
        self.assertFalse(self.builder.exists("test_scenario"))


if __name__ == "__main__":
    unittest.main()
