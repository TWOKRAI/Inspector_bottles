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
    _missing_counter_keys,
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


class TestStrictCounterNames:
    """Третий вид нуля: ключ написан не так, как публикует сервер.

    Регресс 2026-07-21: проба читала ``system_evict_blocked``, роутер публикует
    ``queue_system_evict_blocked``. Счётчик молча отдавал 0 три прогона подряд —
    включая soak синтетики, где он числился среди доказательств чистоты.
    """

    @staticmethod
    def _server_response(keys) -> dict:
        # router_id — якорь: без него ответ не опознаётся как статистика роутера.
        stats = {k: 0 for k in keys}
        stats["router_id"] = "seg-router"
        return {"result": {"router_stats": stats}}

    def test_all_expected_keys_present_is_clean(self):
        assert _missing_counter_keys(self._server_response(_COUNTER_KEYS)) == []

    def test_typo_in_key_is_detected(self):
        server_keys = [k for k in _COUNTER_KEYS if k != "frame_torn_reads"]
        assert _missing_counter_keys(self._server_response(server_keys)) == ["frame_torn_reads"]

    def test_regression_2026_07_21_is_caught(self):
        """Именно тот случай: сервер публикует queue_system_evict_blocked,
        а проба спросила бы system_evict_blocked."""
        server_keys = [k for k in _COUNTER_KEYS if k != "queue_system_evict_blocked"]
        server_keys.append("system_evict_blocked")  # старое (неверное) имя

        missing = _missing_counter_keys(self._server_response(server_keys))

        assert "queue_system_evict_blocked" in missing

    def test_empty_response_is_not_a_name_mismatch(self):
        """Недоступный процесс — не повод объявлять имена сломанными."""
        assert _missing_counter_keys({"result": {}}) == []

    def test_garbage_payload_is_not_a_name_mismatch(self):
        """Мусор в обёртке разворачивается в непустой словарь без единого якоря —
        честный ответ «судить не могу», а не «сломаны все 11 имён»."""
        assert _missing_counter_keys({"result": "boom"}) == []
        assert _missing_counter_keys({"result": {"error": "no handler"}}) == []

    def test_verdict_is_misconfigured_not_clean(self):
        summary = _summarize([_sample(300), _sample(600)], missing_keys=["frame_torn_reads"])

        assert summary["verdict"] == "PROBE_MISCONFIGURED"
        assert summary["missing_keys"] == ["frame_torn_reads"]

    def test_misconfigured_wins_over_clean_samples(self):
        """Чистые сэмплы не должны маскировать невалидную пробу."""
        summary = _summarize([_sample(300), _sample(600)], synthetic=False, missing_keys=["queue_data_evicted"])
        assert summary["verdict"] == "PROBE_MISCONFIGURED"

    def test_no_missing_keys_keeps_normal_verdict(self):
        assert _summarize([_sample(300), _sample(600)], missing_keys=[])["verdict"] == "CLEAN"


class TestBackpressureTier:
    """Сброс кадра — дефект на синтетике и норма на живом тракте.

    Эмпирика 2026-07-21: 10-мин прогон webcam_sketch дал seg.frame_loan_exhausted
    476 → 2722 при torn/stale/pickle = 0, всплески совпали с просадками TEED до
    17 FPS. Это спроектированная backpressure (шапка рецепта: TEED 15-20 FPS
    против камеры 21-25), и красный вердикт по ней приучает вердикт не читать.
    """

    def test_synthetic_treats_drop_as_defect(self):
        summary = _summarize(
            [_sample(300), _sample(600, camera_0=_proc(counters={"frame_loan_exhausted": 2722}))],
            synthetic=True,
        )
        assert summary["verdict"] == "FINDINGS"
        assert any("frame_loan_exhausted" in f for f in summary["findings"])

    def test_live_reports_drop_without_failing_verdict(self):
        summary = _summarize(
            [_sample(300), _sample(600, camera_0=_proc(counters={"frame_loan_exhausted": 2722}))],
            synthetic=False,
        )
        assert summary["verdict"] == "CLEAN_WITH_BACKPRESSURE"
        assert summary["findings"] == []
        assert summary["backpressure"]["camera_0.frame_loan_exhausted"]["total"] == 2722

    def test_live_reports_rate_not_just_total(self):
        """Стартовый всплеск и устойчивый сброс должны различаться — считаем прирост."""
        summary = _summarize(
            [
                _sample(300, camera_0=_proc(counters={"frame_loan_exhausted": 400})),
                _sample(600, camera_0=_proc(counters={"frame_loan_exhausted": 1000})),
            ],
            synthetic=False,
        )
        entry = summary["backpressure"]["camera_0.frame_loan_exhausted"]
        assert entry["delta"] == 600
        assert entry["per_sec"] == 2.0

    def test_live_still_fails_on_real_leak(self):
        """Послабление касается ТОЛЬКО backpressure: битые данные красны везде."""
        summary = _summarize(
            [
                _sample(300),
                _sample(
                    600,
                    camera_0=_proc(counters={"frame_loan_exhausted": 2722, "frame_torn_reads": 1}),
                ),
            ],
            synthetic=False,
        )
        assert summary["verdict"] == "FINDINGS"
        assert any("frame_torn_reads" in f for f in summary["findings"])

    def test_clean_live_run_stays_clean(self):
        assert _summarize([_sample(300), _sample(600)], synthetic=False)["verdict"] == "CLEAN"
