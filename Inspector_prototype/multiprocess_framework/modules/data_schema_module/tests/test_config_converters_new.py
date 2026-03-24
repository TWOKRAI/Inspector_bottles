# -*- coding: utf-8 -*-
"""
Тесты для config_converters (container/config_converters.py).

Покрывает:
    - config_to_dict: вызов build(), ошибка без build()
    - configs_to_dicts: несколько конфигов
    - build_process_with_workers: без воркеров, с воркерами
    - process(): алиас build_process_with_workers
    - HasBuild протокол
"""
import unittest

from data_schema_module import (
    config_to_dict,
    configs_to_dicts,
    build_process_with_workers,
    process,
    HasBuild,
    SchemaBase,
    FieldMeta,
)
from typing import Annotated, Tuple


# =============================================================================
# Вспомогательные конфиги
# =============================================================================

class ProcessConfig:
    """Конфиг процесса с build()."""

    def build(self) -> Tuple[str, dict]:
        return ("main_process", {
            "class": "app.processes.MainProcess",
            "queues": {"system": {"maxsize": 100}},
            "priority": "normal",
        })


class WorkerConfig:
    """Конфиг воркера с build()."""

    def __init__(self, name: str = "worker_1", interval: float = 1.0):
        self._name = name
        self._interval = interval

    def build(self) -> Tuple[str, dict]:
        return (self._name, {
            "class": "app.workers.Worker",
            "config": {"interval": self._interval},
        })


class SchemaBasedConfig(SchemaBase):
    """Конфиг на основе SchemaBase с build()."""
    timeout: Annotated[float, FieldMeta("Таймаут", min=0.0, max=60.0)] = 5.0
    retries: int = 3

    def build(self) -> Tuple[str, dict]:
        return ("schema_process", self.model_dump())


# =============================================================================
# Тесты config_to_dict
# =============================================================================

class TestConfigToDict(unittest.TestCase):
    """Тесты config_to_dict."""

    def test_basic_build(self):
        config = ProcessConfig()
        name, d = config_to_dict(config)
        self.assertEqual(name, "main_process")
        self.assertEqual(d["class"], "app.processes.MainProcess")
        self.assertIn("queues", d)

    def test_worker_config(self):
        config = WorkerConfig("my_worker", 2.0)
        name, d = config_to_dict(config)
        self.assertEqual(name, "my_worker")
        self.assertEqual(d["config"]["interval"], 2.0)

    def test_schema_based_config(self):
        config = SchemaBasedConfig(timeout=10.0, retries=5)
        name, d = config_to_dict(config)
        self.assertEqual(name, "schema_process")
        self.assertEqual(d["timeout"], 10.0)
        self.assertEqual(d["retries"], 5)

    def test_without_build_raises_type_error(self):
        with self.assertRaises(TypeError) as ctx:
            config_to_dict({"name": "test"})
        self.assertIn("build", str(ctx.exception))

    def test_integer_raises_type_error(self):
        with self.assertRaises(TypeError):
            config_to_dict(123)

    def test_none_raises_type_error(self):
        with self.assertRaises(TypeError):
            config_to_dict(None)

    def test_string_raises_type_error(self):
        with self.assertRaises(TypeError):
            config_to_dict("not_a_config")


# =============================================================================
# Тесты configs_to_dicts
# =============================================================================

class TestConfigsToDicts(unittest.TestCase):
    """Тесты configs_to_dicts."""

    def test_multiple_configs(self):
        result = configs_to_dicts(
            ProcessConfig(),
            WorkerConfig("w1"),
            WorkerConfig("w2"),
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], "main_process")
        self.assertEqual(result[1][0], "w1")
        self.assertEqual(result[2][0], "w2")

    def test_single_config(self):
        result = configs_to_dicts(ProcessConfig())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "main_process")

    def test_empty_returns_empty_list(self):
        result = configs_to_dicts()
        self.assertEqual(result, [])

    def test_result_is_list_of_tuples(self):
        result = configs_to_dicts(WorkerConfig("w1"), WorkerConfig("w2"))
        for item in result:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)
            self.assertIsInstance(item[0], str)
            self.assertIsInstance(item[1], dict)


# =============================================================================
# Тесты build_process_with_workers
# =============================================================================

class TestBuildProcessWithWorkers(unittest.TestCase):
    """Тесты build_process_with_workers."""

    def test_without_workers(self):
        name, d = build_process_with_workers(ProcessConfig())
        self.assertEqual(name, "main_process")
        self.assertNotIn("workers", d)

    def test_with_one_worker(self):
        name, d = build_process_with_workers(
            ProcessConfig(),
            WorkerConfig("worker_1"),
        )
        self.assertEqual(name, "main_process")
        self.assertIn("workers", d)
        self.assertIn("worker_1", d["workers"])

    def test_with_multiple_workers(self):
        name, d = build_process_with_workers(
            ProcessConfig(),
            WorkerConfig("w1"),
            WorkerConfig("w2"),
            WorkerConfig("w3"),
        )
        self.assertIn("workers", d)
        self.assertIn("w1", d["workers"])
        self.assertIn("w2", d["workers"])
        self.assertIn("w3", d["workers"])
        self.assertEqual(len(d["workers"]), 3)

    def test_worker_data_preserved(self):
        name, d = build_process_with_workers(
            ProcessConfig(),
            WorkerConfig("my_worker", interval=0.5),
        )
        worker_data = d["workers"]["my_worker"]
        self.assertEqual(worker_data["config"]["interval"], 0.5)

    def test_process_data_preserved_with_workers(self):
        name, d = build_process_with_workers(
            ProcessConfig(),
            WorkerConfig("w1"),
        )
        self.assertEqual(d["class"], "app.processes.MainProcess")
        self.assertIn("queues", d)

    def test_schema_based_process_with_workers(self):
        name, d = build_process_with_workers(
            SchemaBasedConfig(timeout=15.0),
            WorkerConfig("w1"),
        )
        self.assertEqual(name, "schema_process")
        self.assertEqual(d["timeout"], 15.0)
        self.assertIn("workers", d)


# =============================================================================
# Тесты process() — алиас
# =============================================================================

class TestProcessAlias(unittest.TestCase):
    """Тесты алиаса process()."""

    def test_process_equals_build_process_with_workers(self):
        proc_config = ProcessConfig()
        worker_config = WorkerConfig("w1")

        result_process = process(proc_config, worker_config)
        # Создаём новые экземпляры для второго вызова
        result_build = build_process_with_workers(ProcessConfig(), WorkerConfig("w1"))

        self.assertEqual(result_process[0], result_build[0])
        self.assertEqual(result_process[1]["class"], result_build[1]["class"])

    def test_process_without_workers(self):
        name, d = process(ProcessConfig())
        self.assertEqual(name, "main_process")
        self.assertNotIn("workers", d)

    def test_process_with_workers(self):
        name, d = process(ProcessConfig(), WorkerConfig("w1"), WorkerConfig("w2"))
        self.assertIn("workers", d)
        self.assertEqual(len(d["workers"]), 2)


# =============================================================================
# Тесты HasBuild протокол
# =============================================================================

class TestHasBuildProtocol(unittest.TestCase):
    """Тесты HasBuild протокол."""

    def test_process_config_implements_has_build(self):
        config = ProcessConfig()
        self.assertIsInstance(config, HasBuild)

    def test_worker_config_implements_has_build(self):
        config = WorkerConfig()
        self.assertIsInstance(config, HasBuild)

    def test_schema_based_config_implements_has_build(self):
        config = SchemaBasedConfig()
        self.assertIsInstance(config, HasBuild)

    def test_plain_dict_does_not_implement_has_build(self):
        self.assertNotIsInstance({"name": "test"}, HasBuild)

    def test_object_without_build_does_not_implement(self):
        class NoBuild:
            pass
        self.assertNotIsInstance(NoBuild(), HasBuild)


if __name__ == "__main__":
    unittest.main()
