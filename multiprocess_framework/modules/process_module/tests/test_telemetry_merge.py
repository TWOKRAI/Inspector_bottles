"""Контракт-тесты build_worker_telemetry + merge-батчинг (E6/Task 5.7).

Проверяем:
  - паритет: собранные листья == прежний набор set-путей;
  - агрегат state.fps/latency_ms по running-воркерам;
  - None когда публиковать нечего;
  - **число сообщений**: публикатор шлёт ОДИН proxy.merge вместо 3W+2 proxy.set
    (снижение ~в W раз) — свойство через fake-proxy со счётчиком.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_worker_telemetry,
)


def _workers(n: int = 3) -> dict:
    """W воркеров: все running с hz и cycle_duration_ms."""
    return {
        f"w{i}": {
            "status": "running",
            "effective_hz": 10.0 + i,
            "cycle_duration_ms": 5.0 + i,
        }
        for i in range(n)
    }


class TestBuildWorkerTelemetry:
    def test_path_is_process_prefix(self) -> None:
        path, _ = build_worker_telemetry(_workers(2), "proc")
        assert path == "processes.proc"

    def test_per_worker_leaves(self) -> None:
        _, data = build_worker_telemetry(_workers(2), "proc")
        assert data["workers"]["w0"] == {
            "status": "running",
            "effective_hz": 10.0,
            "cycle_duration_ms": 5.0,
        }
        assert data["workers"]["w1"]["effective_hz"] == 11.0

    def test_aggregate_state(self) -> None:
        _, data = build_worker_telemetry(_workers(3), "proc")
        # fps = max(hz) = 12.0; latency_ms = max(cycle) = 7.0
        assert data["state"]["fps"] == 12.0
        assert data["state"]["latency_ms"] == 7.0

    def test_status_only_worker_no_hz(self) -> None:
        """Воркер со status без hz/lat → только status; агрегата нет → без state."""
        result = build_worker_telemetry({"w0": {"status": "idle"}}, "proc")
        assert result is not None
        _, data = result
        assert data["workers"]["w0"] == {"status": "idle"}
        assert "state" not in data

    def test_empty_returns_none(self) -> None:
        assert build_worker_telemetry({}, "proc") is None

    def test_non_dict_workers_skipped(self) -> None:
        result = build_worker_telemetry({"bad": "nope", "w0": {"status": "running", "effective_hz": 5.0}}, "p")
        assert result is not None
        _, data = result
        assert "bad" not in data["workers"]

    def test_input_not_mutated(self) -> None:
        w = _workers(2)
        import copy

        snap = copy.deepcopy(w)
        build_worker_telemetry(w, "proc")
        assert w == snap


class _CountingProxy:
    """Fake StateProxy: считает set/merge вызовы."""

    def __init__(self) -> None:
        self.set_calls = 0
        self.merge_calls = 0
        self.merged: list[tuple[str, dict]] = []

    def set(self, path: str, value: object) -> None:
        self.set_calls += 1

    def merge(self, path: str, data: dict) -> None:
        self.merge_calls += 1
        self.merged.append((path, data))


class _FakeServices:
    def __init__(self, proxy: object, name: str = "proc") -> None:
        self._state_proxy = proxy
        self.name = name

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...


class TestMergeBatching:
    def test_one_merge_not_3w_plus_2_sets(self) -> None:
        """Публикатор шлёт РОВНО один merge и ноль set для W воркеров."""
        W = 4
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy))

        hb._publish_metrics_to_tree(_workers(W))

        assert proxy.merge_calls == 1, "ожидался ровно один merge (батч)"
        assert proxy.set_calls == 0, "прямых set быть не должно (иначе не батч)"
        # payload содержит всех W воркеров + агрегат — один субтри-merge
        path, data = proxy.merged[0]
        assert path == "processes.proc"
        assert len(data["workers"]) == W
        assert "state" in data

    def test_no_workers_no_message(self) -> None:
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy))
        hb._publish_metrics_to_tree({})
        assert proxy.merge_calls == 0
        assert proxy.set_calls == 0


class _FakeRouter:
    def __init__(self, stats: dict) -> None:
        self._stats = stats

    def get_stats(self) -> dict:
        return {"router": self._stats}


class _FakeServicesRouter:
    def __init__(self, proxy: object, router: object, name: str = "proc") -> None:
        self._state_proxy = proxy
        self.router_manager = router
        self.name = name

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...


class TestH8RouterShmStatsPublish:
    """H8 (Ф7 G.3): SHM-счётчики router'а публикуются в дерево (state/heartbeat),
    не только через pull-introspect (иначе вкладка Pipeline их не видит)."""

    def test_publishes_shm_counters_when_nonzero(self) -> None:
        proxy = _CountingProxy()
        router = _FakeRouter({"frame_pickle_fallbacks": 2, "frame_torn_reads": 5, "frame_boundary_crossings": 100})
        hb = ProcessHeartbeat(_FakeServicesRouter(proxy, router))
        hb._publish_router_shm_stats_to_tree()
        assert proxy.merge_calls == 1
        path, data = proxy.merged[0]
        assert path == "processes.proc.state.shm"
        # Ф7 G.4.a: queue_data_evicted добавлен в тот же publish (0, т.к. в статах нет).
        assert data == {
            "pickle_fallbacks": 2,
            "torn_reads": 5,
            "boundary_crossings": 100,
            "queue_data_evicted": 0,
            "queue_system_evict_blocked": 0,
        }

    def test_publishes_when_only_queue_evicted_nonzero(self) -> None:
        """Ф7 G.4.a: дроп data-очереди публикуется, даже если SHM-счётчики нулевые
        (gate включает queue_data_evicted — иначе тихий data-дроп не виден в state)."""
        proxy = _CountingProxy()
        router = _FakeRouter(
            {"frame_pickle_fallbacks": 0, "frame_torn_reads": 0, "frame_boundary_crossings": 0, "queue_data_evicted": 9}
        )
        hb = ProcessHeartbeat(_FakeServicesRouter(proxy, router))
        hb._publish_router_shm_stats_to_tree()
        assert proxy.merge_calls == 1
        _, data = proxy.merged[0]
        assert data["queue_data_evicted"] == 9

    def test_publishes_when_only_system_blocked_nonzero(self) -> None:
        """Ф7 G.4.a: блокировка вытеснения system-очереди публикуется (control-plane
        backpressure виден в state, симметрично data_evicted)."""
        proxy = _CountingProxy()
        router = _FakeRouter(
            {
                "frame_pickle_fallbacks": 0,
                "frame_torn_reads": 0,
                "frame_boundary_crossings": 0,
                "queue_data_evicted": 0,
                "queue_system_evict_blocked": 4,
            }
        )
        hb = ProcessHeartbeat(_FakeServicesRouter(proxy, router))
        hb._publish_router_shm_stats_to_tree()
        assert proxy.merge_calls == 1
        _, data = proxy.merged[0]
        assert data["queue_system_evict_blocked"] == 4

    def test_noop_when_all_zero(self) -> None:
        proxy = _CountingProxy()
        router = _FakeRouter(
            {"frame_pickle_fallbacks": 0, "frame_torn_reads": 0, "frame_boundary_crossings": 0, "queue_data_evicted": 0}
        )
        hb = ProcessHeartbeat(_FakeServicesRouter(proxy, router))
        hb._publish_router_shm_stats_to_tree()
        assert proxy.merge_calls == 0  # чисто → не засоряем дерево

    def test_noop_without_router(self) -> None:
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServicesRouter(proxy, None))
        hb._publish_router_shm_stats_to_tree()
        assert proxy.merge_calls == 0
