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


def test_delete_subtree_root_purges_all_descendants() -> None:
    """Удаление узла-корня поддерева чистит все листья под ним (не только точный ключ).

    tree_store.delete() шлёт ОДНУ дельту на корень поддерева. Без очистки по
    префиксу листья (fps/latency/uptime) остаются навсегда в _state/_history —
    snapshot/history отдают данные по несуществующей сущности.
    """
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.fps", 25.0)
    m.ingest("processes.cam.state.latency_ms", 12.0)
    m.ingest("processes.cam.state.uptime", 100.0)
    # Сосед с общим СТРОКОВЫМ префиксом — не должен пострадать.
    m.ingest("processes.cam2.state.fps", 30.0)

    m.ingest("processes.cam", None, deleted=True)

    # Всё поддерево cam вычищено из снимка И истории.
    assert m.snapshot("processes.cam") == {}
    assert m.history("processes.cam.state.fps") == []
    assert m.history("processes.cam.state.latency_ms") == []
    assert m.history("processes.cam.state.uptime") == []
    # Сосед cam2 цел (в снимке и в истории).
    assert m.get("processes.cam2.state.fps") == 30.0
    assert len(m.history("processes.cam2.state.fps")) == 1


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


# --------------------------------------------------------------------------- #
#  Инъекция clock + экспорт/импорт истории (flight recorder, D.4)              #
# --------------------------------------------------------------------------- #


def test_default_clock_is_wall_clock_bit_for_bit() -> None:
    """Характеризация: без инъекции clock ts точки истории — time.time (прежнее поведение).

    Пин ДО добавления параметра clock: дефолт обязан остаться time.time,
    иначе live-путь (GUI/headless) молча сменил бы ось времени истории.
    """
    m = TelemetryReadModel()
    before = time.time()
    m.ingest("processes.cam.state.fps", 1.0)
    after = time.time()
    ((ts, _val),) = m.history("processes.cam.state.fps")
    assert before <= ts <= after, "дефолтный clock должен быть time.time (wall-clock)"


def test_injected_clock_stamps_history_ts() -> None:
    """Инъекция clock: точки истории несут значение из clock, а не time.time."""
    ticks = iter([100.0, 200.0, 300.0])
    m = TelemetryReadModel(clock=lambda: next(ticks))
    m.ingest("processes.cam.state.fps", 1.0)
    m.ingest("processes.cam.state.fps", 2.0)
    assert m.history("processes.cam.state.fps") == [(100.0, 1.0), (200.0, 2.0)]


def test_export_history_snapshot() -> None:
    ticks = iter([10.0, 20.0])
    m = TelemetryReadModel(clock=lambda: next(ticks))
    m.ingest("processes.cam.state.fps", 5.0)
    m.ingest("processes.cam.state.latency_ms", 12.0)
    exported = m.export_history()
    assert exported == {
        "processes.cam.state.fps": [(10.0, 5.0)],
        "processes.cam.state.latency_ms": [(20.0, 12.0)],
    }


def test_export_import_history_round_trip() -> None:
    """export → import восстанавливает буферы бит-в-бит (записанные ts)."""
    ticks = iter([1.0, 2.0, 3.0])
    src = TelemetryReadModel(clock=lambda: next(ticks))
    src.ingest("processes.cam.state.fps", 5.0)
    src.ingest("processes.cam.state.fps", 6.0)
    src.ingest("processes.cam.state.uptime", 100.0)
    exported = src.export_history()

    dst = TelemetryReadModel()  # дефолтный clock — не влияет на импорт
    dst.import_history(exported)
    assert dst.export_history() == exported
    # ts истории — записанные, не время импорта.
    assert dst.history("processes.cam.state.fps") == [(1.0, 5.0), (2.0, 6.0)]


def test_import_history_respects_maxlen() -> None:
    """Серия длиннее окна усекается до maxlen (хвост), как при живом накоплении."""
    m = TelemetryReadModel(window_sec=3.0, sample_hz=1.0)  # maxlen = 3
    m.import_history({"processes.cam.state.fps": [(float(i), float(i)) for i in range(6)]})
    assert m.history("processes.cam.state.fps") == [(3.0, 3.0), (4.0, 4.0), (5.0, 5.0)]


def test_import_history_skips_malformed_points() -> None:
    m = TelemetryReadModel()
    m.import_history(
        {
            "processes.cam.state.fps": [
                (1.0, 5.0),
                ("bad_ts", 6.0),  # нечисловой ts — пропуск
                (2.0, "bad_val"),  # нечисловое значение — пропуск
                (3.0,),  # неполная точка — пропуск
                (4.0, 7.0),
            ]
        }
    )
    assert m.history("processes.cam.state.fps") == [(1.0, 5.0), (4.0, 7.0)]


def test_export_history_excludes_empty() -> None:
    """Пустых буферов в экспорте нет (нечисловые пути истории не заводят)."""
    m = TelemetryReadModel()
    m.ingest("processes.cam.state.status", "running")  # не число → нет буфера
    assert m.export_history() == {}


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
