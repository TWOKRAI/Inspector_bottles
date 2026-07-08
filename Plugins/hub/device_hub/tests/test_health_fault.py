# -*- coding: utf-8 -*-
"""Fault-тесты device_hub: смерть драйвера изолирована (Ф3.4 M-race-1).

Принцип **contain → report → isolate**: per-device tick-воркер обязан
СОДЕРЖАТЬ падение своего драйвера (``drv.tick`` кидает исключение), НЕ роняя
поток и НЕ затрагивая соседние устройства. Эталон паттерна —
``Plugins/sources/capture/tests/test_health_fault.py``.

Проверяем на РЕАЛЬНОМ tick_loop плагина (замыкание из ``_ensure_device_workers``):
    - падающий драйвер тикает N раз — исключение поймано, поток не упал;
    - каждый упавший tick публикует ``devices.state.<id>.last_error`` (сигнал
      ошибки растёт — на этой базе честный счётчик роста ошибок);
    - ВТОРОЕ (здоровое) устройство продолжает публиковать snapshot — сосед жив;
    - хаб (менеджер) после отказа полностью работоспособен, supervisor
      (``_ensure_device_workers``) не падает.

Инъекция драйверов в ``_manager._drivers`` — штатный тестовый приём зоны
(см. test_lifecycle_regressions.py), гейту test_no_private_access НЕ подчиняется.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from Services.device_hub.registry.entry import DeviceEntry
from Plugins.hub.device_hub.plugin import DeviceHubPlugin

from .conftest import make_ctx

#: Сколько тиков отрабатывает каждый драйвер до самоостановки (детерминизм).
_TICKS = 5


class _RecordingStateProxy:
    """State-proxy, запоминающий все set/merge (потокобезопасно)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def set(self, path: str, data: Any) -> None:
        with self._lock:
            self.calls.append(("set", path))

    def merge(self, path: str, data: Any) -> None:
        with self._lock:
            self.calls.append(("merge", path))

    def count_suffix(self, suffix: str) -> int:
        with self._lock:
            return sum(1 for _op, path in self.calls if path.endswith(suffix))


class _FaultyDriver:
    """Драйвер, чей tick всегда кидает — синтетика «железо выдернуто»."""

    def __init__(self, entry: DeviceEntry) -> None:
        self.entry = entry
        self.is_connected = True
        self.reconnect_exhausted = False
        self.last_io = None
        self.desired_connected = True
        self.stats = {"tx_err": 0}
        self.tick_calls = 0

    def tick(self, stop_evt: threading.Event) -> dict | None:
        self.tick_calls += 1
        if self.tick_calls >= _TICKS:
            stop_evt.set()  # самоостановка после N тиков (детерминизм)
        raise RuntimeError("драйвер выдернут (синтетика)")


class _HealthyDriver:
    """Здоровый сосед: tick стабильно отдаёт snapshot."""

    def __init__(self, entry: DeviceEntry) -> None:
        self.entry = entry
        self.is_connected = True
        self.reconnect_exhausted = False
        self.last_io = None
        self.desired_connected = True
        self.stats = {"tx_ok": 0}
        self.tick_calls = 0

    def tick(self, stop_evt: threading.Event) -> dict | None:
        self.tick_calls += 1
        if self.tick_calls >= _TICKS:
            stop_evt.set()
        return {"quality": "good", "value": self.tick_calls}


def _entry(dev_id: str) -> DeviceEntry:
    """Минимальная запись реестра с быстрым poll-интервалом."""
    return DeviceEntry(id=dev_id, name=dev_id, kind="generic_modbus", params={"poll_interval_s": 0.0})


def _run_tick_worker(fn: Any) -> tuple[threading.Thread, list[BaseException]]:
    """Запустить tick_loop в потоке; вернуть (поток, список пойманных исключений)."""
    stop_evt = threading.Event()
    pause_evt = threading.Event()
    escaped: list[BaseException] = []

    def runner() -> None:
        try:
            fn(stop_evt, pause_evt)
        except BaseException as exc:  # pragma: no cover — сигнал утечки исключения
            escaped.append(exc)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t, escaped


class TestDriverFaultIsolation:
    """Смерть одного драйвера не роняет tick-поток, хаб и соседа."""

    def _prime(self, tmp_path: Path) -> tuple[DeviceHubPlugin, _RecordingStateProxy, _FaultyDriver, _HealthyDriver]:
        """Сконфигурировать плагин, вживить faulty+healthy драйверы, поднять воркеры."""
        registry_file = tmp_path / "devices.yaml"
        proxy = _RecordingStateProxy()
        ctx = make_ctx({"registry_path": str(registry_file)}, state_proxy=proxy, tmp_registry=registry_file)

        plugin = DeviceHubPlugin()
        plugin.configure(ctx)

        faulty = _FaultyDriver(_entry("faulty"))
        healthy = _HealthyDriver(_entry("healthy"))
        # Штатная тестовая инъекция драйверов (как в test_lifecycle_regressions)
        plugin._manager._drivers["faulty"] = faulty
        plugin._manager._drivers["healthy"] = healthy
        plugin._desired_connected["faulty"] = True
        plugin._desired_connected["healthy"] = True

        # Реальный tick_loop создаётся здесь (замыкание make_tick_fn)
        plugin._ensure_device_workers()
        return plugin, proxy, faulty, healthy

    def test_faulty_tick_contained_neighbor_alive(self, tmp_path: Path) -> None:
        """Падающий драйвер тикает N раз, поток не падает, сосед публикует snapshot."""
        plugin, proxy, faulty, healthy = self._prime(tmp_path)

        f_fn = plugin._ctx.worker_manager.workers["dev_faulty"]["fn"]
        h_fn = plugin._ctx.worker_manager.workers["dev_healthy"]["fn"]

        t_f, esc_f = _run_tick_worker(f_fn)
        t_h, esc_h = _run_tick_worker(h_fn)
        t_f.join(timeout=5)
        t_h.join(timeout=5)

        # Потоки завершились штатно — исключение не утекло из tick_loop (contain)
        assert not t_f.is_alive() and not t_h.is_alive()
        assert esc_f == [] and esc_h == []
        # Падающий драйвер отработал все N тиков (каждый — с исключением)
        assert faulty.tick_calls == _TICKS
        # Сосед не пострадал — тикал независимо
        assert healthy.tick_calls == _TICKS

    def test_error_signal_grows(self, tmp_path: Path) -> None:
        """Каждый упавший tick публикует last_error — сигнал ошибки растёт."""
        plugin, proxy, faulty, _healthy = self._prime(tmp_path)

        f_fn = plugin._ctx.worker_manager.workers["dev_faulty"]["fn"]
        t_f, _esc = _run_tick_worker(f_fn)
        t_f.join(timeout=5)

        # last_error опубликован на каждый упавший tick (растущий счётчик ошибок)
        assert proxy.count_suffix("devices.state.faulty.last_error") == _TICKS

    def test_neighbor_publishes_snapshots(self, tmp_path: Path) -> None:
        """Здоровый сосед публикует status на каждый тик (жив, не заглушён отказом)."""
        plugin, proxy, _faulty, _healthy = self._prime(tmp_path)

        h_fn = plugin._ctx.worker_manager.workers["dev_healthy"]["fn"]
        t_h, _esc = _run_tick_worker(h_fn)
        t_h.join(timeout=5)

        assert proxy.count_suffix("devices.state.healthy.status") == _TICKS

    def test_hub_and_supervisor_survive(self, tmp_path: Path) -> None:
        """После отказа хаб работоспособен, supervisor не падает."""
        plugin, _proxy, _faulty, _healthy = self._prime(tmp_path)

        f_fn = plugin._ctx.worker_manager.workers["dev_faulty"]["fn"]
        t_f, _esc = _run_tick_worker(f_fn)
        t_f.join(timeout=5)

        # Хаб (менеджер) отвечает через публичный snapshot-API — не завис/не сломан
        assert plugin._manager.device_count() == 0  # реестр пуст (драйверы вживлены прямо)
        assert isinstance(plugin._manager.snapshot_registry(), list)
        assert "faulty" in plugin._manager.connected_ids()
        assert plugin.cmd_device_list({}).get("status") == "ok"
        # Supervisor-шаг повторно не падает после отказа драйвера
        plugin._ensure_device_workers()
