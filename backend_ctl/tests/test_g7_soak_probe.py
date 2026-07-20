# -*- coding: utf-8 -*-
"""Тесты чистых функций soak-пробы Ф7 G.7 Фазы 3.

Тестируем ровно то, что можно проверить БЕЗ подъёма системы: разбор ответа
``introspect.router_stats``, сведение воркеров к метрикам процесса и логику
вердикта по утечкам. Сам прогон soak — живой инструмент (2ч), в гейт не входит;
та же граница, что в ``test_g1_perf_probe.py``.
"""

from __future__ import annotations

from backend_ctl.probes.g7_soak_probe import (
    _COUNTER_KEYS,
    _counters,
    _summarize,
    _worker_metrics,
)


def _proc(
    *,
    counters: dict | None = None,
    rss: float | None = 72.0,
    pid: int | None = 100,
    fps: float | None = 21.3,
) -> dict:
    """Секция одного процесса в сэмпле (только поля, которые читает _summarize)."""
    return {
        "fps": fps,
        "cycles": 1000,
        "perf_probes": {},
        "pid": pid,
        "rss_mb": rss,
        "counters": {**dict.fromkeys(_COUNTER_KEYS, 0), **(counters or {})},
    }


def _sample(elapsed: float, **processes) -> dict:
    """Сэмпл нового (универсального по топологии) формата."""
    return {"elapsed_sec": elapsed, "processes": processes or {"camera_0": _proc()}}


class TestCounters:
    def test_unwraps_nested_router_stats(self):
        res = {"result": {"router_stats": {"frame_torn_reads": 3, "frame_slots_released": 10}}}
        assert _counters(res)["frame_torn_reads"] == 3
        assert _counters(res)["frame_slots_released"] == 10

    def test_missing_counter_becomes_zero(self):
        assert _counters({"result": {"router_stats": {}}})["frame_loan_exhausted"] == 0

    def test_non_dict_payload_does_not_raise(self):
        """Ответ неожиданной формы не должен ронять soak на 90-й минуте."""
        assert _counters({"result": "boom"}) == dict.fromkeys(_COUNTER_KEYS, 0)


class TestWorkerMetrics:
    def test_takes_leading_worker_hz(self):
        """Темп процесса = максимальный effective_hz, имена воркеров не зашиты."""
        workers = {"capture": {"effective_hz": 21.3, "cycles": 500}, "idle": {"effective_hz": 0.5, "cycles": 10}}
        assert _worker_metrics(workers)["fps"] == 21.3
        assert _worker_metrics(workers)["cycles"] == 500

    def test_collects_probes_only_where_present(self):
        workers = {"a": {"perf_probes": {"capture": 1}}, "b": {}}
        assert list(_worker_metrics(workers)["perf_probes"]) == ["a"]

    def test_empty_workers_do_not_raise(self):
        assert _worker_metrics({})["fps"] is None
        assert _worker_metrics("не dict")["fps"] is None


class TestSummarize:
    def test_clean_run_has_no_findings(self):
        summary = _summarize([_sample(300), _sample(600)])
        assert summary["verdict"] == "CLEAN"
        assert summary["findings"] == []

    def test_leak_counter_is_reported(self):
        summary = _summarize([_sample(300), _sample(600, camera_0=_proc(counters={"frame_torn_reads": 2}))])
        assert summary["verdict"] == "FINDINGS"
        assert any("frame_torn_reads = 2" in f for f in summary["findings"])

    def test_released_growth_is_not_a_finding(self):
        """slots_released растёт по построению — это работа, а не дефект."""
        summary = _summarize([_sample(300), _sample(600, camera_0=_proc(counters={"frame_slots_released": 99999}))])
        assert summary["verdict"] == "CLEAN"

    def test_handle_cache_growth_is_reported(self):
        """Резидуал G.5: рост кэша на инкарнацию под zero-copy."""
        summary = _summarize(
            [
                _sample(300, camera_0=_proc(counters={"frame_handle_cache_size": 4})),
                _sample(600, camera_0=_proc(counters={"frame_handle_cache_size": 9})),
            ]
        )
        assert summary["verdict"] == "FINDINGS"
        assert any("frame_handle_cache_size" in f for f in summary["findings"])

    def test_stable_handle_cache_is_not_a_finding(self):
        summary = _summarize(
            [
                _sample(300, camera_0=_proc(counters={"frame_handle_cache_size": 4})),
                _sample(600, camera_0=_proc(counters={"frame_handle_cache_size": 4})),
            ]
        )
        assert summary["verdict"] == "CLEAN"

    def test_rss_growth_over_20pct_is_reported(self):
        summary = _summarize([_sample(300, camera_0=_proc(rss=70.0)), _sample(600, camera_0=_proc(rss=90.0))])
        assert summary["verdict"] == "FINDINGS"
        assert any("RSS" in f for f in summary["findings"])

    def test_rss_noise_under_threshold_is_ignored(self):
        """Мелкие колебания RSS — не утечка; иначе soak будет кричать всегда."""
        summary = _summarize([_sample(300, camera_0=_proc(rss=70.0)), _sample(600, camera_0=_proc(rss=74.0))])
        assert summary["verdict"] == "CLEAN"

    def test_missing_rss_does_not_crash(self):
        """psutil мог не отдать RSS — вердикт всё равно должен считаться."""
        summary = _summarize([_sample(300, camera_0=_proc(rss=None)), _sample(600, camera_0=_proc(rss=None))])
        assert summary["verdict"] == "CLEAN"

    def test_process_restart_is_reported(self):
        """Смена pid на soak = процесс падал и поднимался — молчать нельзя."""
        summary = _summarize([_sample(300, camera_0=_proc(pid=100)), _sample(600, camera_0=_proc(pid=777))])
        assert summary["verdict"] == "FINDINGS"
        assert any("pid сменился" in f for f in summary["findings"])

    def test_failed_process_section_is_reported(self):
        summary = _summarize([_sample(300), _sample(600, camera_0={"error": "timeout"})])
        assert summary["verdict"] == "FINDINGS"
        assert any("не снялся" in f for f in summary["findings"])

    def test_multi_process_topology_is_walked(self):
        """Прод-рецепт = 7 процессов: находка в любом из них должна всплыть."""
        summary = _summarize(
            [
                _sample(300, camera_0=_proc(), seg=_proc(), lines=_proc()),
                _sample(600, camera_0=_proc(), seg=_proc(counters={"frame_stale_drops": 5}), lines=_proc()),
            ]
        )
        assert summary["verdict"] == "FINDINGS"
        assert any("seg.frame_stale_drops = 5" in f for f in summary["findings"])
        assert set(summary["fps_first_last"]) == {"camera_0", "seg", "lines"}

    def test_no_samples_is_loud(self):
        assert _summarize([])["verdict"] == "NO_SAMPLES"
