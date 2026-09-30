"""Слепые acceptance-тесты 4.8a: `fields.extract_fields`.

Источник истины — `plans/transport-single-policy/task-4.8.md`, п. 5 публичного API.
Ожидаемые значения — литералы из спеки (реальные ответы стенда `a0457ee8`).
"""

from __future__ import annotations

import importlib

SHM_KEYS = {"bytes_written", "bytes_read", "bytes_mapped", "stale_drops", "torn_reads"}


def _extract(levels):
    return importlib.import_module("scripts.capacity_bench.fields").extract_fields(levels)


def _processor_levels():
    return {
        "workers": {
            "data_receiver": {"transport_ms": 26.6, "tick_ms": 5.0},
            "pipeline_executor": {"queue_wait_ms": 1097.9},
        },
        "state": {
            "fps": 58.1,
            "cpu": {"cores": 1.69, "percent": 40.0},
            "plugin_ms": {"color_mask": 11.5, "blob_detector": 1.9},
            "shm": {
                "bytes_written": 1_000_000,
                "bytes_read": 900_000,
                "bytes_mapped": 8_388_608,
                "stale_drops": 3,
                "torn_reads": 0,
                "unrelated_gauge": 77,  # должен быть отфильтрован
            },
        },
    }


def test_extract_fields_processor_sample():
    assert _extract(_processor_levels()) == {
        "hz": 58.1,
        "inner_cores": 1.69,
        "plugin_ms": {"color_mask": 11.5, "blob_detector": 1.9},
        "queue_wait_ms": 1097.9,
        "transport_ms": 26.6,
        "pacer_late": None,
        "shm": {
            "bytes_written": 1_000_000,
            "bytes_read": 900_000,
            "bytes_mapped": 8_388_608,
            "stale_drops": 3,
            "torn_reads": 0,
        },
    }


def test_extract_fields_camera_sample():
    levels = {
        "workers": {"source_producer_camera_service": {"pacer_late": 456}},
        "state": {"fps": 24.9, "cpu": {"cores": 0.31}},
    }
    result = _extract(levels)
    assert result["pacer_late"] == 456
    assert result["queue_wait_ms"] is None
    assert result["transport_ms"] is None
    assert result["plugin_ms"] == {}
    assert result["hz"] == 24.9
    assert result["inner_cores"] == 0.31


def test_extract_fields_empty_dict_is_all_none():
    assert _extract({}) == {
        "hz": None,
        "inner_cores": None,
        "plugin_ms": {},
        "queue_wait_ms": None,
        "transport_ms": None,
        "pacer_late": None,
        "shm": None,
    }


def test_extract_fields_empty_sections_do_not_raise():
    result = _extract({"workers": {}, "state": {}})
    assert result["hz"] is None
    assert result["plugin_ms"] == {}
    assert result["pacer_late"] is None


def test_extract_fields_state_without_cpu_gives_none_cores():
    result = _extract({"state": {"fps": 10.0}})
    assert result["hz"] == 10.0
    assert result["inner_cores"] is None


def test_extract_fields_shm_only_contract_keys():
    shm = _extract(_processor_levels())["shm"]
    assert set(shm) == SHM_KEYS


def test_extract_fields_pacer_late_is_sum_over_workers():
    levels = {"workers": {"a": {"pacer_late": 456}, "b": {"pacer_late": 4}, "c": {"tick": 1}}}
    assert _extract(levels)["pacer_late"] == 460


def test_extract_fields_pacer_late_zero_is_not_none():
    assert _extract({"workers": {"a": {"pacer_late": 0}}})["pacer_late"] == 0


def test_extract_fields_transport_is_max_regardless_of_order():
    """Поле в нескольких воркерах -> максимум (большой и первым, и последним)."""
    big_first = {"workers": {"a": {"transport_ms": 26.6}, "b": {"transport_ms": 3.5}}}
    big_last = {"workers": {"a": {"transport_ms": 3.5}, "b": {"transport_ms": 26.6}}}
    assert _extract(big_first)["transport_ms"] == 26.6
    assert _extract(big_last)["transport_ms"] == 26.6


def test_extract_fields_queue_wait_is_max_regardless_of_order():
    """Трактовка: правило «максимум» из спеки относится и к queue_wait_ms."""
    big_first = {"workers": {"a": {"queue_wait_ms": 1097.9}, "b": {"queue_wait_ms": 4.0}}}
    big_last = {"workers": {"a": {"queue_wait_ms": 4.0}, "b": {"queue_wait_ms": 1097.9}}}
    assert _extract(big_first)["queue_wait_ms"] == 1097.9
    assert _extract(big_last)["queue_wait_ms"] == 1097.9
