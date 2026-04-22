"""Unit-тесты для ProcessorWorkerConfig и AppConfig.worker_configs (Phase 5c)."""

from __future__ import annotations

import sys
from pathlib import Path

_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

import pytest

from backend.processes.processor_worker.config import ProcessorWorkerConfig
from config.app import AppConfig

# AppConfig внутри использует 'multiprocess_prototype_v3.backend...' путь, поэтому
# для isinstance-проверок в тестах all_process_configs/worker_configs используем
# тот же класс, что видит AppConfig — через атрибут __name__ или duck-typing.
# Простой способ: получить класс из реального объекта конфига.
_WorkerConfigClass = AppConfig(worker_pool_size=1).worker_configs[0].__class__


# ---------------------------------------------------------------------------
# Тесты ProcessorWorkerConfig
# ---------------------------------------------------------------------------


class TestProcessorWorkerConfig:
    def test_process_name_matches_worker_index_0(self):
        """worker_index=0 → process_name == 'processor_worker_0'."""
        config = ProcessorWorkerConfig(worker_index=0)
        assert config.process_name == "processor_worker_0"

    def test_process_name_matches_worker_index_1(self):
        """worker_index=1 → process_name == 'processor_worker_1'."""
        config = ProcessorWorkerConfig(worker_index=1)
        assert config.process_name == "processor_worker_1"

    def test_process_name_matches_worker_index_2(self):
        """worker_index=2 → process_name == 'processor_worker_2'."""
        config = ProcessorWorkerConfig(worker_index=2)
        assert config.process_name == "processor_worker_2"

    def test_result_shm_name_index_0(self):
        """worker_index=0 → result_shm_name == 'worker_0_result'."""
        config = ProcessorWorkerConfig(worker_index=0)
        assert config.result_shm_name == "worker_0_result"

    def test_result_shm_name_index_1(self):
        """worker_index=1 → result_shm_name == 'worker_1_result'."""
        config = ProcessorWorkerConfig(worker_index=1)
        assert config.result_shm_name == "worker_1_result"

    def test_result_shm_name_index_5(self):
        """worker_index=5 → result_shm_name == 'worker_5_result'."""
        config = ProcessorWorkerConfig(worker_index=5)
        assert config.result_shm_name == "worker_5_result"

    def test_process_name_always_matches_worker_index(self):
        """process_name всегда соответствует worker_index (model_post_init)."""
        for idx in range(5):
            config = ProcessorWorkerConfig(worker_index=idx)
            assert config.process_name == f"processor_worker_{idx}"

    def test_result_shm_name_pattern(self):
        """result_shm_name всегда имеет паттерн 'worker_{index}_result'."""
        for idx in range(5):
            config = ProcessorWorkerConfig(worker_index=idx)
            assert config.result_shm_name == f"worker_{idx}_result"


# ---------------------------------------------------------------------------
# Тесты AppConfig.worker_configs
# ---------------------------------------------------------------------------


class TestAppConfigWorkerConfigs:
    def test_worker_pool_size_3_returns_3_configs(self):
        """worker_pool_size=3 → worker_configs содержит 3 конфига."""
        cfg = AppConfig(worker_pool_size=3)
        assert len(cfg.worker_configs) == 3

    def test_worker_pool_size_0_returns_empty_list(self):
        """worker_pool_size=0 → worker_configs == []."""
        cfg = AppConfig(worker_pool_size=0)
        assert cfg.worker_configs == []

    def test_worker_configs_have_correct_indices(self):
        """worker_configs с worker_pool_size=3 → индексы 0, 1, 2."""
        cfg = AppConfig(worker_pool_size=3)
        indices = [c.worker_index for c in cfg.worker_configs]
        assert indices == [0, 1, 2]

    def test_worker_configs_all_are_processor_worker_config(self):
        """Все элементы worker_configs — ProcessorWorkerConfig (по классу из AppConfig)."""
        cfg = AppConfig(worker_pool_size=3)
        for c in cfg.worker_configs:
            # Проверяем через класс того же модуля, который использует AppConfig
            assert isinstance(c, _WorkerConfigClass)

    def test_worker_configs_process_names_unique(self):
        """Все process_name в worker_configs уникальны."""
        cfg = AppConfig(worker_pool_size=4)
        names = [c.process_name for c in cfg.worker_configs]
        assert len(names) == len(set(names))

    def test_worker_pool_size_1_returns_single_config(self):
        """worker_pool_size=1 → 1 конфиг с index 0."""
        cfg = AppConfig(worker_pool_size=1)
        assert len(cfg.worker_configs) == 1
        assert cfg.worker_configs[0].worker_index == 0


# ---------------------------------------------------------------------------
# Тесты AppConfig.all_process_configs()
# ---------------------------------------------------------------------------


class TestAppConfigAllProcessConfigs:
    def test_worker_pool_size_2_contains_2_worker_configs_at_end(self):
        """all_process_configs() с worker_pool_size=2 → последние 2 — worker configs."""
        cfg = AppConfig(worker_pool_size=2)
        all_configs = cfg.all_process_configs()

        # Последние 2 — worker-конфиги (используем класс из _WorkerConfigClass)
        last_two = all_configs[-2:]
        assert all(isinstance(c, _WorkerConfigClass) for c in last_two)

    def test_worker_pool_size_2_contains_exactly_2_worker_configs(self):
        """all_process_configs() с worker_pool_size=2 → ровно 2 ProcessorWorkerConfig."""
        cfg = AppConfig(worker_pool_size=2)
        all_configs = cfg.all_process_configs()

        worker_configs = [c for c in all_configs if isinstance(c, _WorkerConfigClass)]
        assert len(worker_configs) == 2

    def test_worker_pool_size_0_contains_no_worker_configs(self):
        """all_process_configs() с worker_pool_size=0 → нет ProcessorWorkerConfig."""
        cfg = AppConfig(worker_pool_size=0)
        all_configs = cfg.all_process_configs()

        # Проверяем по имени process_class — нет воркеров
        worker_configs = [
            c for c in all_configs
            if hasattr(c, "worker_index")
        ]
        assert len(worker_configs) == 0

    def test_all_process_configs_worker_indices_correct(self):
        """Worker-конфиги в all_process_configs() имеют правильные индексы 0, 1."""
        cfg = AppConfig(worker_pool_size=2)
        all_configs = cfg.all_process_configs()

        worker_configs = [c for c in all_configs if isinstance(c, _WorkerConfigClass)]
        indices = [c.worker_index for c in worker_configs]
        assert indices == [0, 1]

    def test_all_process_configs_contains_non_worker_processes(self):
        """all_process_configs() содержит процессы помимо worker'ов (processor, gui и т.д.)."""
        cfg = AppConfig(worker_pool_size=0)
        all_configs = cfg.all_process_configs()

        # Должны быть camera, processor, renderer, robot, database, gui (6+ процессов)
        assert len(all_configs) >= 5
