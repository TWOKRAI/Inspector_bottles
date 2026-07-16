# -*- coding: utf-8 -*-
"""Тесты рантайм-переконфигурации publisher-gate (PC 3.1).

Acceptance 3.1:
  - ``heartbeat.reconfigure_telemetry({...})`` живьём меняет gate: метрика была
    enabled → стала disabled → следующий payload без неё (БЕЗ пересоздания процесса);
  - ``None`` → gate off (все метрики каждый тик, backward-compat);
  - смена атомарна: новый gate — другой объект, старый не мутируется.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import GATED_METRICS


def _workers(n: int = 2) -> dict:
    return {f"w{i}": {"status": "running", "effective_hz": 10.0 + i, "cycle_duration_ms": 5.0 + i} for i in range(n)}


class _CountingProxy:
    def __init__(self) -> None:
        self.merged: list[tuple[str, dict]] = []
        self.set_calls = 0

    def set(self, path: str, value: object) -> None:
        self.set_calls += 1

    def merge(self, path: str, data: dict) -> None:
        self.merged.append((path, data))


class _FakeServices:
    def __init__(self, proxy: object, *, name: str = "proc") -> None:
        self._state_proxy = proxy
        self.router_manager = None
        self.name = name
        self._config: dict = {}
        self._health_state = None

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...


class TestReconfigureGate:
    def test_none_disables_gate(self) -> None:
        """None → gate off (обратная совместимость: все метрики каждый тик)."""
        hb = ProcessHeartbeat(_FakeServices(_CountingProxy()))
        hb.reconfigure_telemetry({"metrics": {"fps": {"enabled": False}}})
        assert hb._telemetry_gate is not None
        hb.reconfigure_telemetry(None)
        assert hb._telemetry_gate is None

    def test_live_enable_to_disable(self) -> None:
        """Метрика была enabled → live-reconfigure disabled → gate её больше не выдаёт."""
        hb = ProcessHeartbeat(_FakeServices(_CountingProxy()))

        hb.reconfigure_telemetry({"metrics": {"fps": {"enabled": True}}})
        gate1 = hb._telemetry_gate
        assert "fps" in gate1.due_metrics(now=0.0)

        hb.reconfigure_telemetry({"metrics": {"fps": {"enabled": False}}})
        gate2 = hb._telemetry_gate
        # Атомарная смена: новый объект, старый не тронут.
        assert gate2 is not gate1
        assert "fps" not in gate2.due_metrics(now=0.0)
        # Старый gate не мутирован сменой (изоляция состояния _next_due).
        assert "fps" in gate1.due_metrics(now=1000.0)

    def test_empty_dict_activates_default_throttle(self) -> None:
        """Пустой publish → дефолт 1.0с (осознанная явная команда, gate активен)."""
        hb = ProcessHeartbeat(_FakeServices(_CountingProxy()))
        hb.reconfigure_telemetry({})
        gate = hb._telemetry_gate
        assert gate is not None
        # Все метрики созревают на первом тике (next_due=0), затем реже 1.0с.
        assert gate.due_metrics(now=0.0) == set(GATED_METRICS)
        assert gate.due_metrics(now=0.5) == set()  # <1.0с — зажато

    def test_payload_drops_disabled_metric_after_reconfigure(self) -> None:
        """E2E: после live-reconfigure выключенная метрика исчезает из merge-payload."""
        proxy = _CountingProxy()
        hb = ProcessHeartbeat(_FakeServices(proxy))

        # Выключаем per-worker частоту/цикл — status обязан остаться (вне гейта).
        hb.reconfigure_telemetry(
            {"metrics": {"effective_hz": {"enabled": False}, "cycle_duration_ms": {"enabled": False}}}
        )
        gate = hb._telemetry_gate
        allowed = gate.due_metrics(now=0.0)
        hb._publish_metrics_to_tree(_workers(2), allowed)

        assert proxy.merged, "нет публикации"
        _, data = proxy.merged[-1]
        wp = data["workers"]["w0"]
        assert "effective_hz" not in wp
        assert "cycle_duration_ms" not in wp
        assert wp["status"] == "running"  # status always-on

    def test_reconfigure_matches_build_gate_from_config(self) -> None:
        """reconfigure(section) эквивалентен построению gate из get_config на старте."""
        cfg_section = {"default_interval_sec": 2.0, "metrics": {"shm": {"enabled": False}}}

        svc = _FakeServices(_CountingProxy())
        svc._config = {"telemetry": {"publish": cfg_section}}
        hb_boot = ProcessHeartbeat(svc)
        boot_gate = hb_boot._build_telemetry_gate()

        hb_rt = ProcessHeartbeat(_FakeServices(_CountingProxy()))
        hb_rt.reconfigure_telemetry(cfg_section)
        rt_gate = hb_rt._telemetry_gate

        assert boot_gate.due_metrics(now=0.0) == rt_gate.due_metrics(now=0.0)
        # shm выключен в обоих.
        assert "shm" not in boot_gate.due_metrics(now=100.0)
        assert "shm" not in rt_gate.due_metrics(now=100.0)
