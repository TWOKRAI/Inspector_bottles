# -*- coding: utf-8 -*-
"""Тесты чистых хелперов perf-пробника Ф7 G.1/G.7 (``backend_ctl.probes.g1_perf_probe``).

Только форма разбора dict-ответа ``introspect.router_stats`` — без запуска системы.
Гейт лесенки G.7 (§0/§1) читает счётчики потерь SHM через :func:`_shm_counters`;
эти тесты фиксируют, что набор извлекается робастно к обёртке и к пропускам.
"""

from __future__ import annotations

from backend_ctl.probes.g1_perf_probe import _COUNTER_KEYS, _shm_counters

# Реальная форма (снято с живого бэкенда): внешний конверт success + payload под
# result, счётчики — под router_stats. Парсер обязан спуститься и достать их.
_RS_RESP = {
    "success": True,
    "result": {
        "success": True,
        "process": "consumer",
        "router_stats": {
            "frame_boundary_crossings": 290,
            "frame_torn_reads": 0,
            "frame_stale_drops": 0,
            "frame_loan_exhausted": 0,
            "frame_slots_released": 288,
            "frame_slots_reclaimed": 0,
            "frame_handle_cache_size": 3,
            "frame_pickle_fallbacks": 0,
            "queue_data_evicted": 0,
            "queue_system_evict_blocked": 0,
        },
    },
}


def test_extracts_all_counter_keys():
    """Все ключи набора извлекаются как int из вложенного router_stats."""
    got = _shm_counters(_RS_RESP)
    assert set(got) == set(_COUNTER_KEYS)
    assert got["frame_boundary_crossings"] == 290
    assert got["frame_slots_released"] == 288
    assert got["frame_handle_cache_size"] == 3
    assert all(isinstance(v, int) for v in got.values())


def test_missing_counters_default_to_zero():
    """Отсутствующий счётчик → 0 (частичный router_stats без падения)."""
    resp = {"result": {"router_stats": {"frame_boundary_crossings": 5}}}
    got = _shm_counters(resp)
    assert got["frame_boundary_crossings"] == 5
    assert got["frame_torn_reads"] == 0
    assert got["frame_slots_released"] == 0


def test_flat_router_stats_without_envelope():
    """Ответ без вложенности result → router_stats берётся с верхнего уровня."""
    resp = {"router_stats": {"frame_torn_reads": 2}}
    got = _shm_counters(resp)
    assert got["frame_torn_reads"] == 2


def test_garbage_response_all_zero():
    """Не-dict / пустой / кривой ответ → весь набор нулевой, без исключения."""
    for bad in (None, {}, {"result": None}, {"result": {"router_stats": "nope"}}, 42, "x"):
        got = _shm_counters(bad)  # type: ignore[arg-type]
        assert set(got) == set(_COUNTER_KEYS)
        assert all(v == 0 for v in got.values())


def test_none_counter_value_coerced_to_zero():
    """Явный None в счётчике → 0 (guard ``int(x or 0)``)."""
    resp = {"result": {"router_stats": {"frame_stale_drops": None}}}
    assert _shm_counters(resp)["frame_stale_drops"] == 0
