"""Тесты TelemetryReadModel — generic Qt-free ядро read-model телеметрии.

Проверяют (без Qt — чистое ядро):
  * late-binding: snapshot/get актуальны сразу после ingest;
  * граница префикса snapshot: 'processes.cam' не течёт в 'processes.cam2';
  * deleted убирает путь;
  * кольцевые буферы: maxlen-вытеснение, since-фильтр, wall-clock ts;
  * generic: пустой tracked_suffixes → история не копится; свой набор суффиксов;
  * инвариант: ядро не имеет транспортных полей (router/proxy/subscribe).
"""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.telemetry_readmodel_module import (
    DEFAULT_TRACKED_SUFFIXES,
    TelemetryReadModel,
)


# --------------------------------------------------------------------------- #
#  read-model / late-binding                                                   #
# --------------------------------------------------------------------------- #


def test_snapshot_available_immediately_after_ingest() -> None:
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.fps", 25.0)
    m.ingest("processes.cam.state.latency_ms", 12.0)
    assert m.get("processes.cam.state.fps") == 25.0
    assert m.snapshot("processes.cam") == {
        "processes.cam.state.fps": 25.0,
        "processes.cam.state.latency_ms": 12.0,
    }


def test_initial_cache_primes_snapshot() -> None:
    m = TelemetryReadModel(initial_cache={"processes.cam.state.fps": 30.0})
    assert m.get("processes.cam.state.fps") == 30.0


def test_prime_ignores_non_string_paths() -> None:
    m = TelemetryReadModel(initial_cache={"ok.path": 1.0, 42: "bad"})
    assert m.get("ok.path") == 1.0
    assert m.snapshot("") == {"ok.path": 1.0}


def test_snapshot_prefix_boundary_no_sibling_leak() -> None:
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.fps", 25.0)
    m.ingest("processes.cam2.state.fps", 9.0)
    assert m.snapshot("processes.cam") == {"processes.cam.state.fps": 25.0}


def test_snapshot_exact_prefix_match_included() -> None:
    """Путь, равный самому prefix (без точки-суффикса), попадает в снимок."""
    m = TelemetryReadModel(tracked_suffixes=())
    m.ingest("processes.cam", {"nested": 1})
    assert m.snapshot("processes.cam") == {"processes.cam": {"nested": 1}}


def test_empty_prefix_returns_full_snapshot() -> None:
    m = TelemetryReadModel()
    m.ingest("a.b", 1.0)
    m.ingest("c.d", 2.0)
    assert m.snapshot("") == {"a.b": 1.0, "c.d": 2.0}


def test_deleted_removes_path() -> None:
    m = TelemetryReadModel()
    m.ingest("processes.a.state.fps", 1.0)
    m.ingest("processes.a.state.fps", None, deleted=True)
    assert m.get("processes.a.state.fps", "MISS") == "MISS"


def test_delete_unknown_path_is_noop() -> None:
    m = TelemetryReadModel()
    m.ingest("processes.ghost.state.fps", None, deleted=True)  # не бросает
    assert m.snapshot("") == {}


# --------------------------------------------------------------------------- #
#  Инвариант: ядро без транспорта                                              #
# --------------------------------------------------------------------------- #


def test_read_model_has_no_transport_fields() -> None:
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.fps", 25.0)
    for forbidden in ("subscribe", "ensure_subscription", "_router", "_proxy", "_gui_proxy"):
        assert not hasattr(m, forbidden), f"ядро неожиданно имеет '{forbidden}'"


# --------------------------------------------------------------------------- #
#  Кольцевые буферы истории                                                    #
# --------------------------------------------------------------------------- #


def test_history_records_tracked_numeric_only() -> None:
    assert ".state.fps" in DEFAULT_TRACKED_SUFFIXES
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.fps", 25.0)
    m.ingest("processes.cam.state.status", "running")  # не число/не трек
    assert [v for _ts, v in m.history("processes.cam.state.fps")] == [25.0]
    assert m.history("processes.cam.state.status") == []


def test_history_bool_is_not_numeric() -> None:
    """bool — не число для истории (регресс: True != 1.0 в спарклайне)."""
    m = TelemetryReadModel(tracked_suffixes=(".state.fps",))
    m.ingest("processes.cam.state.fps", True)
    assert m.history("processes.cam.state.fps") == []


def test_history_ring_buffer_evicts_oldest() -> None:
    m = TelemetryReadModel(window_sec=5.0, sample_hz=1.0)  # maxlen = 5
    for i in range(8):
        m.ingest("processes.cam.state.fps", float(i))
    vals = [v for _ts, v in m.history("processes.cam.state.fps")]
    assert vals == [3.0, 4.0, 5.0, 6.0, 7.0]


def test_history_since_filters_range() -> None:
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.fps", 1.0)
    time.sleep(0.05)
    cutoff = time.time()
    time.sleep(0.05)
    m.ingest("processes.cam.state.fps", 2.0)
    recent = m.history("processes.cam.state.fps", since=cutoff)
    assert [v for _ts, v in recent] == [2.0]


def test_history_ts_is_wall_clock() -> None:
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.fps", 1.0)
    ((ts, _val),) = m.history("processes.cam.state.fps")
    assert abs(ts - time.time()) < 2.0, "ring-ts должен быть wall-clock (Unix-epoch)"


def test_history_empty_for_unknown_path() -> None:
    m = TelemetryReadModel()
    assert m.history("processes.nope.state.fps") == []


# --------------------------------------------------------------------------- #
#  Generic: tracked_suffixes — параметр                                        #
# --------------------------------------------------------------------------- #


def test_empty_tracked_suffixes_disables_history() -> None:
    m = TelemetryReadModel(tracked_suffixes=())
    m.ingest("processes.cam.state.fps", 25.0)
    assert m.get("processes.cam.state.fps") == 25.0
    assert m.history("processes.cam.state.fps") == []


def test_custom_tracked_suffixes() -> None:
    m = TelemetryReadModel(tracked_suffixes=(".custom.metric",))
    m.ingest("app.node.custom.metric", 7.0)
    m.ingest("processes.cam.state.fps", 25.0)  # дефолтный суффикс — не трек
    assert [v for _ts, v in m.history("app.node.custom.metric")] == [7.0]
    assert m.history("processes.cam.state.fps") == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
