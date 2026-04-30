"""Тесты ScenarioManager (извлечён из Dispatcher)."""

import unittest

from ..core.scenarios import ScenarioManager


class TestScenarioManager(unittest.TestCase):
    """Прямое тестирование ScenarioManager без Dispatcher."""

    def setUp(self):
        self.mgr = ScenarioManager()

    def test_create_scenario(self):
        self.assertTrue(self.mgr.create_scenario("s1", "desc", {"k": 1}))
        self.assertFalse(self.mgr.create_scenario("s1"))
        info = self.mgr.get_scenario_info("s1")
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "s1")

    def test_delete_scenario(self):
        self.mgr.create_scenario("tmp")
        self.assertTrue(self.mgr.delete_scenario("tmp"))
        self.assertFalse(self.mgr.delete_scenario("tmp"))

    def test_add_handler_to_scenario(self):
        self.mgr.create_scenario("pipe")

        def h1(d):
            return d

        self.assertTrue(
            self.mgr.add_handler_to_scenario("pipe", "a", h1, stage=1)
        )
        self.assertFalse(
            self.mgr.add_handler_to_scenario("missing", "a", h1, stage=1)
        )

    def test_dispatch_scenario_success(self):
        self.mgr.create_scenario("ok")

        def step(data):
            return {"data": data}

        self.mgr.add_handler_to_scenario("ok", "s", step, stage=1)
        result = self.mgr.dispatch_scenario("ok", {"data": {"v": 1}})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scenario"], "ok")
        self.assertEqual(len(result["stages"]), 1)
        self.assertEqual(result["final_result"], {"data": {"v": 1}})

    def test_dispatch_scenario_stop_on_error(self):
        self.mgr.create_scenario("err")

        def good(_):
            return {}

        def bad(_):
            raise ValueError("x")

        self.mgr.add_handler_to_scenario("err", "g", good, stage=1)
        self.mgr.add_handler_to_scenario("err", "b", bad, stage=2)

        r = self.mgr.dispatch_scenario("err", {"data": {}}, stop_on_error=True)
        self.assertEqual(r["status"], "error")
        self.assertEqual(len(r["stages"]), 2)
        self.assertIn("final_error", r)

    def test_dispatch_scenario_passes_result_between_stages(self):
        self.mgr.create_scenario("chain")

        def first(_):
            return {"data": {"n": 2}}

        def second(data):
            return {"doubled": data.get("n", 0) * 2}

        self.mgr.add_handler_to_scenario("chain", "f", first, stage=1)
        self.mgr.add_handler_to_scenario("chain", "s", second, stage=2)
        r = self.mgr.dispatch_scenario("chain", {"data": {}})
        self.assertEqual(r["final_result"], {"doubled": 4})

    def test_scenario_not_found(self):
        r = self.mgr.dispatch_scenario("nope", {"data": {}})
        self.assertEqual(r["status"], "error")
        self.assertIn("not found", r["reason"])

    def test_clear(self):
        self.mgr.create_scenario("c")
        self.mgr.clear()
        self.assertFalse(self.mgr.has_scenario("c"))

    def test_has_scenario(self):
        self.assertFalse(self.mgr.has_scenario("x"))
        self.mgr.create_scenario("x")
        self.assertTrue(self.mgr.has_scenario("x"))


if __name__ == "__main__":
    unittest.main()
