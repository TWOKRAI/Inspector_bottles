# -*- coding: utf-8 -*-
"""Тесты perf_probes — per-stage latency-пробы hot path за флагом (HP-1, Ф7 G.1)."""

from unittest.mock import patch

import pytest

from multiprocess_framework.modules.process_module.generic import perf_probes


@pytest.fixture
def probes_on():
    """Включить пробы на время теста (env читается при импорте)."""
    prev = perf_probes._ENABLED
    perf_probes._ENABLED = True
    yield
    perf_probes._ENABLED = prev


@pytest.fixture
def probes_off():
    prev = perf_probes._ENABLED
    perf_probes._ENABLED = False
    yield
    perf_probes._ENABLED = prev


class TestDisabled:
    def test_enabled_false(self, probes_off) -> None:
        assert perf_probes.enabled() is False

    def test_measure_returns_shared_noop_singleton(self, probes_off) -> None:
        """При off measure() не аллоцирует новый объект на каждый вызов —
        всегда один и тот же no-op синглтон (см. class-докстринг LatencyProbes)."""
        probes = perf_probes.LatencyProbes()
        cm1 = probes.measure("capture")
        cm2 = probes.measure("send")
        assert cm1 is cm2 is perf_probes._NOOP_MEASUREMENT

    def test_no_perf_counter_calls_when_disabled(self, probes_off) -> None:
        """Acceptance HP-1: флаг off → ноль вызовов time.perf_counter() на кадр.

        Проверяем буквально: patch'аем perf_counter в модуле perf_probes и
        прогоняем N "кадров" через measure() — счётчик вызовов обязан остаться 0.
        """
        probes = perf_probes.LatencyProbes()
        with patch("multiprocess_framework.modules.process_module.generic.perf_probes.time.perf_counter") as mock_pc:
            for _ in range(50):
                with probes.measure("capture"):
                    pass
                with probes.measure("send"):
                    pass
            mock_pc.assert_not_called()

    def test_no_samples_recorded_when_disabled(self, probes_off) -> None:
        probes = perf_probes.LatencyProbes()
        for _ in range(10):
            with probes.measure("capture"):
                pass
        assert probes.get_stats() == {}


class TestEnabled:
    def test_measure_records_sample(self, probes_on) -> None:
        probes = perf_probes.LatencyProbes()
        with probes.measure("capture"):
            pass
        stats = probes.get_stats()
        assert "capture" in stats
        assert stats["capture"]["count"] == 1
        assert stats["capture"]["p50_ms"] >= 0.0
        assert stats["capture"]["p99_ms"] >= 0.0

    def test_measure_records_even_on_exception(self, probes_on) -> None:
        """Этап всё равно занял время, даже если тело блока бросило — как у
        CycleMetricsRecorder.measure()."""
        probes = perf_probes.LatencyProbes()
        with pytest.raises(ValueError):
            with probes.measure("restore"):
                raise ValueError("boom")
        assert probes.get_stats()["restore"]["count"] == 1

    def test_separate_stages_tracked_independently(self, probes_on) -> None:
        probes = perf_probes.LatencyProbes()
        for _ in range(5):
            with probes.measure("capture"):
                pass
        for _ in range(3):
            with probes.measure("send"):
                pass
        stats = probes.get_stats()
        assert stats["capture"]["count"] == 5
        assert stats["send"]["count"] == 3

    def test_window_bounds_memory(self, probes_on) -> None:
        """Окно ограничено _WINDOW последними замерами — не растёт бесконечно."""
        probes = perf_probes.LatencyProbes()
        for _ in range(perf_probes._WINDOW + 50):
            with probes.measure("capture"):
                pass
        assert probes.get_stats()["capture"]["count"] == perf_probes._WINDOW


class TestSourceProducerIntegration:
    """Интеграция с SourceProducer: perf_probes подмешивается в get_cycle_metrics()
    только когда флаг включён (тот же факад, что FPS/cycle_duration_ms —
    WorkerManager.get_worker_status → heartbeat → GUI)."""

    def test_get_cycle_metrics_no_perf_probes_key_when_disabled(self, probes_off) -> None:
        from multiprocess_framework.modules.process_module.generic.source_producer import (
            SourceProducer,
        )
        from multiprocess_framework.modules.process_module.plugins.base import (
            ProcessModulePlugin,
        )

        class _Src(ProcessModulePlugin):
            name = "src"
            category = "source"

            def configure(self, ctx): ...
            def produce(self) -> list[dict]:
                return []

        producer = SourceProducer(
            plugin=_Src(),
            shm_middleware=None,
            send_fn=lambda t, m: None,
            chain_targets=[],
        )
        assert "perf_probes" not in producer.get_cycle_metrics()

    def test_get_cycle_metrics_has_perf_probes_key_when_enabled(self, probes_on) -> None:
        from multiprocess_framework.modules.process_module.generic.source_producer import (
            SourceProducer,
        )
        from multiprocess_framework.modules.process_module.plugins.base import (
            ProcessModulePlugin,
        )

        class _Src(ProcessModulePlugin):
            name = "src"
            category = "source"

            def configure(self, ctx): ...
            def produce(self) -> list[dict]:
                return []

        producer = SourceProducer(
            plugin=_Src(),
            shm_middleware=None,
            send_fn=lambda t, m: None,
            chain_targets=[],
        )
        metrics = producer.get_cycle_metrics()
        assert "perf_probes" in metrics
        assert metrics["perf_probes"] == {}  # ни одного produce() ещё не было


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
