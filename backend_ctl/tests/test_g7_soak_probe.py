# -*- coding: utf-8 -*-
"""Тесты чистых функций soak-пробы Ф7 G.7 Фазы 3.

Тестируем ровно то, что можно проверить БЕЗ подъёма системы: разбор ответа
``introspect.router_stats`` и логику вердикта по утечкам. Сам прогон soak —
живой инструмент (2ч), в гейт не входит; та же граница, что в
``test_g1_perf_probe.py``.
"""

from __future__ import annotations

from backend_ctl.probes.g7_soak_probe import _COUNTER_KEYS, _counters, _summarize


def _sample(
    elapsed: float, *, source: dict | None = None, consumer: dict | None = None, rss: dict | None = None
) -> dict:
    """Минимальный сэмпл нужной формы (только поля, которые читает _summarize)."""
    zero = dict.fromkeys(_COUNTER_KEYS, 0)
    return {
        "elapsed_sec": elapsed,
        "source_fps": 21.3,
        "consumer_fps": 21.3,
        "counters": {"source": {**zero, **(source or {})}, "consumer": {**zero, **(consumer or {})}},
        "rss_mb": rss if rss is not None else {"synthetic_source": 72.0, "consumer": 66.0},
    }


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


class TestSummarize:
    def test_clean_run_has_no_findings(self):
        summary = _summarize([_sample(300), _sample(600)])
        assert summary["verdict"] == "CLEAN"
        assert summary["findings"] == []

    def test_leak_counter_is_reported(self):
        summary = _summarize([_sample(300), _sample(600, consumer={"frame_torn_reads": 2})])
        assert summary["verdict"] == "FINDINGS"
        assert any("frame_torn_reads = 2" in f for f in summary["findings"])

    def test_released_growth_is_not_a_finding(self):
        """slots_released растёт по построению — это работа, а не дефект."""
        summary = _summarize([_sample(300), _sample(600, source={"frame_slots_released": 99999})])
        assert summary["verdict"] == "CLEAN"

    def test_handle_cache_growth_is_reported(self):
        """Резидуал G.5: рост кэша на инкарнацию под zero-copy."""
        summary = _summarize(
            [
                _sample(300, consumer={"frame_handle_cache_size": 4}),
                _sample(600, consumer={"frame_handle_cache_size": 9}),
            ]
        )
        assert summary["verdict"] == "FINDINGS"
        assert any("frame_handle_cache_size" in f for f in summary["findings"])

    def test_stable_handle_cache_is_not_a_finding(self):
        summary = _summarize(
            [
                _sample(300, consumer={"frame_handle_cache_size": 4}),
                _sample(600, consumer={"frame_handle_cache_size": 4}),
            ]
        )
        assert summary["verdict"] == "CLEAN"

    def test_rss_growth_over_20pct_is_reported(self):
        summary = _summarize(
            [
                _sample(300, rss={"synthetic_source": 70.0, "consumer": 66.0}),
                _sample(600, rss={"synthetic_source": 90.0, "consumer": 66.0}),
            ]
        )
        assert summary["verdict"] == "FINDINGS"
        assert any("RSS" in f for f in summary["findings"])

    def test_rss_noise_under_threshold_is_ignored(self):
        """Мелкие колебания RSS — не утечка; иначе soak будет кричать всегда."""
        summary = _summarize(
            [
                _sample(300, rss={"synthetic_source": 70.0, "consumer": 66.0}),
                _sample(600, rss={"synthetic_source": 74.0, "consumer": 66.0}),
            ]
        )
        assert summary["verdict"] == "CLEAN"

    def test_missing_rss_does_not_crash(self):
        """psutil мог не отдать RSS — вердикт всё равно должен считаться."""
        summary = _summarize([_sample(300, rss={}), _sample(600, rss={})])
        assert summary["verdict"] == "CLEAN"

    def test_no_samples_is_loud(self):
        assert _summarize([])["verdict"] == "NO_SAMPLES"
