# -*- coding: utf-8 -*-
"""Тесты publisher-gate телеметрии (PC 1.2).

Acceptance 1.2:
  - выключенная метрика отсутствует в payload build_worker_telemetry (unit);
  - per-метрика interval прореживает публикацию (симуляция N тиков heartbeat при
    коротком интервале, фейк-время → метрика выходит реже);
  - дефолт (нет конфига) → payload как прежде (характеризация);
  - status/health публикуются даже при выключенных метриках.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs import (
    MetricRule,
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    GATED_METRICS,
    TelemetryGate,
    build_worker_telemetry,
)


def _workers(n: int = 2) -> dict:
    return {f"w{i}": {"status": "running", "effective_hz": 10.0 + i, "cycle_duration_ms": 5.0 + i} for i in range(n)}


# --------------------------------------------------------------------------- #
# build_worker_telemetry — фильтр allowed_metrics
# --------------------------------------------------------------------------- #
class TestBuildFilter:
    def test_none_allowed_is_legacy(self) -> None:
        """allowed_metrics=None → идентично прежнему поведению (характеризация)."""
        path, data = build_worker_telemetry(_workers(2), "proc", None)
        assert path == "processes.proc"
        assert data["workers"]["w0"] == {
            "status": "running",
            "effective_hz": 10.0,
            "cycle_duration_ms": 5.0,
        }
        assert data["state"] == {"fps": 11.0, "latency_ms": 6.0}

    def test_disabled_effective_hz_absent(self) -> None:
        """effective_hz не в allowed → его нет в per-worker payload (status остаётся)."""
        allowed = set(GATED_METRICS) - {"effective_hz"}
        _, data = build_worker_telemetry(_workers(1), "proc", allowed)
        wp = data["workers"]["w0"]
        assert "effective_hz" not in wp
        assert wp["status"] == "running"
        assert "cycle_duration_ms" in wp  # прочие не тронуты

    def test_only_fps(self) -> None:
        """allowed={fps} → нет hz/cycle/latency; есть status + агрегат fps."""
        _, data = build_worker_telemetry(_workers(2), "proc", {"fps"})
        assert data["workers"]["w0"] == {"status": "running"}
        assert data["state"] == {"fps": 11.0}
        assert "latency_ms" not in data["state"]

    def test_empty_allowed_only_status_no_state(self) -> None:
        """allowed=set() (все метрики выключены) → только status, агрегата нет."""
        _, data = build_worker_telemetry(_workers(2), "proc", set())
        assert data["workers"]["w0"] == {"status": "running"}
        assert data["workers"]["w1"] == {"status": "running"}
        assert "state" not in data  # агрегат не считается и не публикуется

    def test_status_always_present(self) -> None:
        """status — вне гейта: присутствует при любом allowed."""
        for allowed in (set(), {"fps"}, {"effective_hz"}):
            _, data = build_worker_telemetry(_workers(1), "proc", allowed)
            assert data["workers"]["w0"]["status"] == "running"

    def test_only_latency_ms_no_fps(self) -> None:
        """allowed={latency_ms} без fps → state={latency_ms}, без fps."""
        _, data = build_worker_telemetry(_workers(2), "proc", {"latency_ms"})
        assert data["state"] == {"latency_ms": 6.0}
        assert "fps" not in data["state"]


# --------------------------------------------------------------------------- #
# TelemetryGate — вкл/выкл + per-метрика rate-limit (фейк-время)
# --------------------------------------------------------------------------- #
class TestGate:
    def test_disabled_metric_never_granted(self) -> None:
        cfg = TelemetryPublishConfig(metrics={"fps": MetricRule(enabled=False)})
        gate = TelemetryGate(cfg)
        for t in (0.0, 1.0, 2.0, 100.0):
            assert "fps" not in gate.due_metrics(now=t)

    def test_interval_thins_publication(self) -> None:
        """fps interval_sec=1.0: за 6 тиков через 0.4с fps выходит реже.

        Трейс next_due: t=0.0 grant→next=1.0; 0.4/0.8 <1.0 skip; t=1.2 grant→next=2.2;
        1.6/2.0 <2.2 skip. Итог: 2 публикации из 6 тиков (без гейта было бы 6).
        """
        cfg = TelemetryPublishConfig(default_interval_sec=1.0)
        gate = TelemetryGate(cfg)
        ticks = [0.0, 0.4, 0.8, 1.2, 1.6, 2.0]
        granted = [t for t in ticks if "fps" in gate.due_metrics(now=t)]
        assert granted == [0.0, 1.2]
        assert len(granted) < len(ticks)

    def test_first_tick_grants_all_enabled(self) -> None:
        """Первый тик (next_due=0) выдаёт все включённые метрики."""
        cfg = TelemetryPublishConfig(default_interval_sec=5.0)
        gate = TelemetryGate(cfg)
        assert gate.due_metrics(now=0.0) == set(GATED_METRICS)

    def test_per_metric_independent_intervals(self) -> None:
        """Разные интервалы у метрик независимы: shm реже, fps чаще."""
        cfg = TelemetryPublishConfig(
            default_interval_sec=1.0,
            metrics={"shm": MetricRule(interval_sec=3.0)},
        )
        gate = TelemetryGate(cfg)
        # t=0 → все; t=1.0 → fps (1.0) созрел, shm (3.0) — нет; t=3.0 → оба.
        assert "shm" in gate.due_metrics(now=0.0)
        d1 = gate.due_metrics(now=1.0)
        assert "fps" in d1 and "shm" not in d1
        d3 = gate.due_metrics(now=3.0)
        assert "fps" in d3 and "shm" in d3

    def test_zero_interval_grants_every_tick(self) -> None:
        """interval_sec=0 → выдаётся на каждом тике (нет троттлинга)."""
        cfg = TelemetryPublishConfig(default_interval_sec=0.0)
        gate = TelemetryGate(cfg)
        for t in (0.0, 0.01, 0.02):
            assert "fps" in gate.due_metrics(now=t)


# --------------------------------------------------------------------------- #
# Интеграция с ProcessHeartbeat
# --------------------------------------------------------------------------- #
class _CountingProxy:
    def __init__(self) -> None:
        self.set_calls = 0
        self.merge_calls = 0
        self.merged: list[tuple[str, dict]] = []
        self.sets: list[tuple[str, object]] = []

    def set(self, path: str, value: object) -> None:
        self.set_calls += 1
        self.sets.append((path, value))

    def merge(self, path: str, data: dict) -> None:
        self.merge_calls += 1
        self.merged.append((path, data))


class _FakeRouter:
    def __init__(self, stats: dict) -> None:
        self._stats = stats

    def get_stats(self) -> dict:
        return {"router": self._stats}


class _FakeServices:
    def __init__(self, proxy: object, *, router: object = None, name: str = "proc", config: dict | None = None) -> None:
        self._state_proxy = proxy
        self.router_manager = router
        self.name = name
        self._config = config or {}
        self._health_state = None

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...


class TestBuildTelemetryGate:
    def test_no_section_no_gate(self) -> None:
        """Нет секции telemetry → гейт None (обратная совместимость)."""
        hb = ProcessHeartbeat(_FakeServices(_CountingProxy(), config={}))
        assert hb._build_telemetry_gate() is None

    def test_section_without_publish_no_gate(self) -> None:
        """Секция telemetry без publish → None."""
        hb = ProcessHeartbeat(_FakeServices(_CountingProxy(), config={"telemetry": {"throttle": {}}}))
        assert hb._build_telemetry_gate() is None

    def test_publish_section_builds_gate(self) -> None:
        cfg = {"telemetry": {"publish": {"metrics": {"fps": {"enabled": False}}}}}
        hb = ProcessHeartbeat(_FakeServices(_CountingProxy(), config=cfg))
        gate = hb._build_telemetry_gate()
        assert gate is not None
        assert "fps" not in gate.due_metrics(now=0.0)


class TestPublishMetricsGated:
    def test_disabled_metric_absent_from_merge(self) -> None:
        """Через _publish_metrics_to_tree: выключенный effective_hz не в merge."""
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy))
        allowed = set(GATED_METRICS) - {"effective_hz", "cycle_duration_ms"}
        hb._publish_metrics_to_tree(_workers(2), allowed)
        assert proxy.merge_calls == 1
        _, data = proxy.merged[0]
        assert "effective_hz" not in data["workers"]["w0"]
        assert data["workers"]["w0"]["status"] == "running"

    def test_none_allowed_backward_compatible(self) -> None:
        """allowed=None (дефолт) → полный payload как раньше."""
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy))
        hb._publish_metrics_to_tree(_workers(2))
        _, data = proxy.merged[0]
        assert "effective_hz" in data["workers"]["w0"]
        assert data["state"] == {"fps": 11.0, "latency_ms": 6.0}


class TestShmGated:
    _STATS = {"frame_pickle_fallbacks": 2, "frame_torn_reads": 5, "frame_boundary_crossings": 100}

    def test_shm_skipped_when_not_allowed(self) -> None:
        """shm не в allowed → нет публикации даже при ненулевых счётчиках."""
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy, router=_FakeRouter(dict(self._STATS))))
        hb._publish_router_shm_stats_to_tree(allowed_metrics={"fps"})  # без shm
        assert proxy.merge_calls == 0

    def test_shm_published_when_allowed(self) -> None:
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy, router=_FakeRouter(dict(self._STATS))))
        hb._publish_router_shm_stats_to_tree(allowed_metrics={"shm"})
        assert proxy.merge_calls == 1
        path, _ = proxy.merged[0]
        assert path == "processes.proc.state.shm"

    def test_shm_none_backward_compatible(self) -> None:
        """allowed=None → shm публикуется (как раньше)."""
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy, router=_FakeRouter(dict(self._STATS))))
        hb._publish_router_shm_stats_to_tree()
        assert proxy.merge_calls == 1


class TestHealthAlwaysOn:
    def test_health_publishes_despite_disabled_metrics(self) -> None:
        """Инвариант: health публикуется вне зависимости от гейта метрик.

        _publish_health_to_tree не принимает allowed_metrics и не гейтится — свежий
        HealthState (dirty со старта) публикует начальный snapshot всегда.
        """
        from multiprocess_framework.modules.process_module.health.state import HealthState

        proxy = _CountingProxy()
        services = _FakeServices(proxy)
        services._health_state = HealthState()
        hb = ProcessHeartbeat(services)
        hb._publish_health_to_tree()
        assert proxy.set_calls > 0  # health ушёл в дерево несмотря на любые гейты метрик
