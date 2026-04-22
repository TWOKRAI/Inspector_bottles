"""
Тесты для config_converters — Dict at Boundary.
"""

import pytest

from ..container.config_converters import (
    config_to_dict,
    configs_to_dicts,
    build_process_with_workers,
    process,
)


class MockProcessConfig:
    """Мок конфига процесса с build()."""

    def build(self) -> tuple[str, dict]:
        return ("test_process", {
            "class": "test.module.ProcessClass",
            "queues": {"system": {"maxsize": 100}},
            "priority": "normal",
        })


class MockWorkerConfig:
    """Мок конфига воркера с build()."""

    def __init__(self, name: str = "worker_1"):
        self._name = name

    def build(self) -> tuple[str, dict]:
        return (self._name, {
            "class": "test.module.WorkerClass",
            "config": {"interval": 1.0},
        })


class TestConfigToDict:
    """Тесты config_to_dict."""

    def test_config_with_build(self) -> None:
        """config_to_dict() вызывает build()."""
        config = MockProcessConfig()
        name, d = config_to_dict(config)

        assert name == "test_process"
        assert d["class"] == "test.module.ProcessClass"
        assert d["queues"]["system"]["maxsize"] == 100

    def test_config_without_build_raises(self) -> None:
        """config без build() raises TypeError."""
        with pytest.raises(TypeError, match="build"):
            config_to_dict({"name": "test"})
        with pytest.raises(TypeError, match="build"):
            config_to_dict(123)


class TestConfigsToDicts:
    """Тесты configs_to_dicts."""

    def test_multiple_configs(self) -> None:
        """configs_to_dicts() преобразует несколько конфигов."""
        result = configs_to_dicts(
            MockProcessConfig(),
            MockWorkerConfig("w1"),
            MockWorkerConfig("w2"),
        )
        assert len(result) == 3
        assert result[0][0] == "test_process"
        assert result[1][0] == "w1"
        assert result[2][0] == "w2"


class TestBuildProcessWithWorkers:
    """Тесты build_process_with_workers."""

    def test_without_workers(self) -> None:
        """build_process_with_workers без воркеров."""
        name, proc_dict = build_process_with_workers(MockProcessConfig())

        assert name == "test_process"
        assert proc_dict["class"] == "test.module.ProcessClass"
        assert "workers" not in proc_dict

    def test_with_workers(self) -> None:
        """build_process_with_workers с воркерами."""
        name, proc_dict = build_process_with_workers(
            MockProcessConfig(),
            MockWorkerConfig("worker_1"),
            MockWorkerConfig("worker_2"),
        )

        assert name == "test_process"
        assert "workers" in proc_dict
        assert "worker_1" in proc_dict["workers"]
        assert "worker_2" in proc_dict["workers"]
        assert proc_dict["workers"]["worker_1"]["class"] == "test.module.WorkerClass"


class TestProcessAlias:
    """Тесты алиаса process()."""

    def test_process_equals_build_process_with_workers(self) -> None:
        """process() эквивалентен build_process_with_workers()."""
        result_process = process(
            MockProcessConfig(),
            MockWorkerConfig("w1"),
        )
        result_build = build_process_with_workers(
            MockProcessConfig(),
            MockWorkerConfig("w1"),
        )
        assert result_process == result_build
