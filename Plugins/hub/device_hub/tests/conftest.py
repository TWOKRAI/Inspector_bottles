"""Фикстуры тестов плагина device_hub."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport


# ------------------------------------------------------------------ #
# Фейковый PluginContext (по образцу robot_io)
# ------------------------------------------------------------------ #


class FakeWorkerManager:
    """Менеджер воркеров: запоминает созданных, но не запускает реально."""

    def __init__(self) -> None:
        self.workers: dict[str, Any] = {}

    def create_worker(self, name: str, fn: Any, cfg: Any = None, auto_start: bool = False) -> None:
        """Запомнить воркер; НЕ стартуем (тесты вызывают fn руками)."""
        self.workers[name] = {"fn": fn, "cfg": cfg, "auto_start": auto_start}

    def stop_worker(self, name: str) -> None:
        """Удалить воркер из реестра."""
        self.workers.pop(name, None)


def make_ctx(
    config: dict | None = None,
    *,
    state_proxy: Any = None,
    tmp_registry: Path | None = None,
) -> MagicMock:
    """Создать фейковый PluginContext.

    Args:
        config:       Конфиг плагина (dict, как из topology YAML).
        state_proxy:  MagicMock или реальный (для проверки merge).
        tmp_registry: Путь к tmp-файлу реестра (для override registry_path).
    """
    ctx = MagicMock()
    cfg = config or {}
    if tmp_registry is not None:
        cfg["registry_path"] = str(tmp_registry)
    ctx.config = cfg
    ctx.registers = None  # локальный register
    ctx.state_proxy = state_proxy or MagicMock()
    ctx.worker_manager = FakeWorkerManager()
    ctx.router_manager = MagicMock()
    ctx.process_name = "devices"
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    return ctx


@pytest.fixture
def sim_core() -> RobotSimCore:
    return RobotSimCore()


@pytest.fixture
def fake_transport(sim_core: RobotSimCore) -> FakeRobotTransport:
    return FakeRobotTransport(sim_core)


@pytest.fixture
def robot_entry() -> DeviceEntry:
    """Запись реестра для робота (tcp)."""
    return DeviceEntry(
        id="robot_main",
        name="Робот Delta",
        kind="robot",
        protocol="delta_universal3",
        transport={"type": "tcp", "host": "192.168.1.7", "port": 502, "unit_id": 2},
        params={"word_order": "little", "feed_poll_s": 0.05, "telemetry_interval_s": 0.5},
    )


@pytest.fixture
def vfd_entry() -> DeviceEntry:
    """Запись реестра для ПЧ (bridge через robot_main)."""
    return DeviceEntry(
        id="vfd_belt",
        name="ПЧ лента",
        kind="vfd",
        protocol="gd20_bridge",
        transport={"type": "bridge", "bridge": "robot_main"},
        params={"freq_max_hz": 50.0, "default_freq_hz": 10.0, "poll_interval_s": 0.5},
    )


@pytest.fixture
def stop_event() -> threading.Event:
    """Stop-event для воркеров."""
    return threading.Event()


@pytest.fixture
def pause_event() -> threading.Event:
    """Pause-event для воркеров (не выставлен)."""
    return threading.Event()
