# -*- coding: utf-8 -*-
"""Проводка ctx.health в PluginContext (Ф2 Task 2.1).

Проверяет, что ctx.health — фасад над процесс-общим HealthState (шарится между
копиями ctx из with_config и достижим для heartbeat через services._health_state).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.health import (
    HealthReporter,
    HealthState,
    publish_health,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


class _FakeProxy:
    def __init__(self) -> None:
        self.sets: list[tuple[str, object]] = []

    def set(self, path: str, value: object) -> None:
        self.sets.append((path, value))


def test_ctx_health_returns_reporter() -> None:
    ctx = PluginContext(services=MockProcessServices(name="cam0"), config={})
    assert isinstance(ctx.health, HealthReporter)


def test_ctx_health_is_cached() -> None:
    ctx = PluginContext(services=MockProcessServices(name="cam0"), config={})
    assert ctx.health is ctx.health


def test_ctx_health_shares_process_state_across_copies() -> None:
    services = MockProcessServices(name="cam0")
    base = PluginContext(services=services, config={})
    a = base.with_config({"x": 1})
    b = base.with_config({"y": 2})

    a.health.report_error(ValueError("e1"))
    b.health.report_error(ValueError("e2"))

    # Обе копии бьют в один агрегат процесса, доступный heartbeat'у через services.
    state = services._health_state
    assert isinstance(state, HealthState)
    assert state.error_count == 2


def test_ctx_health_default_context_is_plugin_name() -> None:
    ctx = PluginContext(services=MockProcessServices(name="cam0"), config={})
    ctx._plugin_name = "camera_service"
    ctx.health.report_error(ValueError("boom"))
    state = ctx.services._health_state
    assert state.snapshot()["last_error"]["context"] == "camera_service"


def test_ctx_health_end_to_end_to_fake_tree() -> None:
    """report_error через ctx.health → publish_health → пути в фейковом дереве."""
    services = MockProcessServices(name="cam0")
    ctx = PluginContext(services=services, config={})
    ctx.health.report_error(RuntimeError("camera lost"), context="grab")

    proxy = _FakeProxy()
    assert publish_health(services._health_state, proxy, services.name) is True
    paths = {p for p, _ in proxy.sets}
    assert "processes.cam0.health.status" in paths
    assert "processes.cam0.health.errors" in paths
    assert "processes.cam0.health.last_error" in paths
