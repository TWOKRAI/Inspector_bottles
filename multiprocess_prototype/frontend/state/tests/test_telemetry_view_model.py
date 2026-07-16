"""Тесты TelemetryViewModel — локальный GUI read-model телеметрии (Ф1 Task 1.1/1.2).

Проверяют:
  * late-binding: snapshot/get актуальны сразу после дельт (без ожидания);
  * коалесинг: один updated-батч на пачку дельт; deleted убирает путь;
  * инвариант: VM не держит router/proxy и не создаёт серверных подписок;
  * кольцевые буферы: maxlen-вытеснение, O(1) append, выборка since.
"""

from __future__ import annotations

import time

import pytest

from multiprocess_prototype.frontend.state.telemetry_view_model import (
    DEFAULT_TRACKED_SUFFIXES,
    TelemetryViewModel,
)


def _delta(path: str, value: object, deleted: bool = False) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": deleted}


# --------------------------------------------------------------------------- #
#  Task 1.1 — read-model / late-binding / коалесинг                            #
# --------------------------------------------------------------------------- #


def test_snapshot_available_immediately_after_delta(qtbot) -> None:
    """Late-binding: snapshot видит значения сразу, синхронно (до event loop)."""
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("processes.cam.state.fps", 25.0))
    vm.on_state_delta(_delta("processes.cam.state.latency_ms", 12.0))
    # snapshot читает read-model, наполняемый синхронно — flush не нужен.
    assert vm.get("processes.cam.state.fps") == 25.0
    assert vm.snapshot("processes.cam") == {
        "processes.cam.state.fps": 25.0,
        "processes.cam.state.latency_ms": 12.0,
    }


def test_initial_cache_primes_snapshot(qtbot) -> None:
    """Первичный снимок (cache gui-proxy) доступен через snapshot без дельт."""
    vm = TelemetryViewModel(initial_cache={"processes.cam.state.fps": 30.0})
    assert vm.get("processes.cam.state.fps") == 30.0


def test_snapshot_prefix_boundary_no_sibling_leak(qtbot) -> None:
    """snapshot('processes.cam') НЕ захватывает 'processes.cam2.*' (общий префикс)."""
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("processes.cam.state.fps", 25.0))
    vm.on_state_delta(_delta("processes.cam2.state.fps", 9.0))
    snap = vm.snapshot("processes.cam")
    assert snap == {"processes.cam.state.fps": 25.0}


def test_updated_emitted_once_per_packet(qtbot) -> None:
    """Три дельты в одном обороте event loop → один updated с батчем из 3."""
    vm = TelemetryViewModel()
    with qtbot.waitSignal(vm.updated, timeout=1000) as blocker:
        vm.on_state_delta(_delta("processes.a.state.fps", 1.0))
        vm.on_state_delta(_delta("processes.b.state.fps", 2.0))
        vm.on_state_delta(_delta("processes.c.state.fps", 3.0))
    batch = dict(blocker.args[0])
    assert batch == {
        "processes.a.state.fps": 1.0,
        "processes.b.state.fps": 2.0,
        "processes.c.state.fps": 3.0,
    }


def test_deleted_removes_path_and_batches_none(qtbot) -> None:
    """deleted убирает путь из read-model, в батч уходит (path, None)."""
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("processes.a.state.fps", 1.0))
    qtbot.wait(5)  # дать первому пакету flush'нуться
    with qtbot.waitSignal(vm.updated, timeout=1000) as blocker:
        vm.on_state_delta(_delta("processes.a.state.fps", None, deleted=True))
    assert vm.get("processes.a.state.fps", "MISS") == "MISS"
    assert dict(blocker.args[0]) == {"processes.a.state.fps": None}


def test_ignores_unrelated_data_types(qtbot) -> None:
    """Сообщения не state_delta/gui_local_metric и без path/value — игнорируются."""
    vm = TelemetryViewModel()
    vm.on_state_delta({"data_type": "log_record", "path": "x", "value": 1})
    vm.on_state_delta({"data_type": "state_delta"})  # без path/value
    assert vm.snapshot("") == {}


def test_gui_local_metric_accepted(qtbot) -> None:
    """gui_local_metric питает тот же read-model (system.chain_fps и т.п.)."""
    vm = TelemetryViewModel()
    vm.on_state_delta({"data_type": "gui_local_metric", "path": "system.chain_fps", "value": 21.3, "deleted": False})
    assert vm.get("system.chain_fps") == 21.3


# --------------------------------------------------------------------------- #
#  Инвариант: VM не создаёт серверных подписок                                 #
# --------------------------------------------------------------------------- #


def test_view_model_creates_no_server_subscriptions(qtbot) -> None:
    """VM не держит router/proxy и не экспонирует subscribe-путей (структурно)."""
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("processes.cam.state.fps", 25.0))
    for forbidden in ("subscribe", "ensure_subscription", "_router", "_proxy", "_gui_proxy"):
        assert not hasattr(vm, forbidden), f"VM неожиданно имеет '{forbidden}'"


# --------------------------------------------------------------------------- #
#  Task 1.2 — кольцевые буферы истории                                         #
# --------------------------------------------------------------------------- #


def test_history_records_tracked_numeric_only(qtbot) -> None:
    """История копится только для отслеживаемых суффиксов и числовых значений."""
    assert ".state.fps" in DEFAULT_TRACKED_SUFFIXES
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("processes.cam.state.fps", 25.0))
    vm.on_state_delta(_delta("processes.cam.state.status", "running"))  # не число/не трек
    assert [v for _ts, v in vm.history("processes.cam.state.fps")] == [25.0]
    assert vm.history("processes.cam.state.status") == []


def test_history_ring_buffer_evicts_oldest(qtbot) -> None:
    """Fixed-size deque: переполнение окна вытесняет старейшие точки."""
    vm = TelemetryViewModel(window_sec=5.0, sample_hz=1.0)  # maxlen = 5
    for i in range(8):
        vm.on_state_delta(_delta("processes.cam.state.fps", float(i)))
    vals = [v for _ts, v in vm.history("processes.cam.state.fps")]
    assert vals == [3.0, 4.0, 5.0, 6.0, 7.0]  # последние 5, старые вытеснены


def test_history_since_filters_range(qtbot) -> None:
    """history(since) отдаёт только точки с ts >= since."""
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta("processes.cam.state.fps", 1.0))
    # Пауза > гранулярности time.monotonic() (на Windows ~16 мс), чтобы ts
    # первой точки был СТРОГО меньше cutoff — иначе грубые часы дают ts == cutoff.
    time.sleep(0.05)
    cutoff = time.monotonic()
    time.sleep(0.05)
    vm.on_state_delta(_delta("processes.cam.state.fps", 2.0))
    recent = vm.history("processes.cam.state.fps", since=cutoff)
    assert [v for _ts, v in recent] == [2.0]


def test_history_empty_for_unknown_path(qtbot) -> None:
    vm = TelemetryViewModel()
    assert vm.history("processes.nope.state.fps") == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
