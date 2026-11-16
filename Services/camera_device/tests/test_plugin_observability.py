# -*- coding: utf-8 -*-
"""Наблюдаемость базы плагина камеры (Task 2.3b): метрики, событийное состояние, `health`, `flight_dump`.

Плагин настоящий, порт — фейк, `PluginContext` — настоящий над `MockProcessServices`. Подменены только приёмники:
`state_proxy` (счёт `merge`), `ctx.health` (фейк инцидентов), `publish_metric`/`record_timing`/`flight_dump`
(запись вызовов). Один тест (`test_настоящие_объекты`) идёт с настоящим `HealthState` и `PluginLevels`.
Ожидаемые числа — литералы из ACCEPTANCE задачи 2.3b. Вызовы, которые могут зависнуть, идут с дедлайном.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from multiprocess_framework.modules.process_module.heartbeat.telemetry import PluginLevels
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import make_port

PROCESS_NAME = "cam_obs"
TREE_PATH = f"processes.{PROCESS_NAME}.state.plugins.camera_device"
LEVELS = {"fps", "frames", "errors", "dropped", "pending", "param_errors_count"}


class _FakeProxy:
    """`state_proxy`: записывает `merge`/`set`/`delete` (потокобезопасно)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.merges: list[tuple[str, dict]] = []
        self.sets: list[tuple[str, object]] = []
        self.deletes: list[str] = []

    def merge(self, path: str, data: dict) -> None:
        with self.lock:
            self.merges.append((path, dict(data)))

    def set(self, path: str, value: object) -> None:
        with self.lock:
            self.sets.append((path, value))

    def delete(self, path: str) -> None:
        with self.lock:
            self.deletes.append(path)

    def merged(self, key: str) -> list:
        with self.lock:
            return [data[key] for _, data in self.merges if key in data]


class _FakeHealth:
    """Фасад `ctx.health`: инциденты и статус."""

    def __init__(self) -> None:
        self.errors: list[tuple[BaseException, str | None]] = []
        self.degraded_reasons: list[str] = []
        self.statuses: list[str] = []

    def report_error(self, exc, context=None, throttle=None, **fields) -> None:
        self.errors.append((exc, context))

    def degraded(self, reason: str) -> None:
        self.degraded_reasons.append(reason)

    def set_status(self, status, reason=None) -> None:
        self.statuses.append(str(status))

    def record_success(self) -> None:
        pass


class _Rig:
    """Плагин над фейковым портом; `real_health=True` оставляет настоящий `ctx.health` и `PluginLevels`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, port=None, real: bool = False, **cfg) -> None:
        self.port = port if port is not None else make_port(frame_period_s=0.02)
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: self.port)
        config = {"auto_start": False, "camera_id": 3, "device_select": "first", **cfg}
        self.levels = PluginLevels() if real else None
        self.services = MockProcessServices(name=PROCESS_NAME, config=config, plugin_levels=self.levels)
        self.wm = WorkerManager("test_cam_obs")
        self.services.worker_manager = self.wm
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.proxy = _FakeProxy()
        self.ctx.state_proxy = self.proxy
        self.health = _FakeHealth()
        self.published: list[tuple[str, object]] = []
        self.timings: list[tuple[str, float]] = []
        self.dumps: list[tuple[str, dict]] = []
        if not real:
            self.ctx._health_reporter = self.health
        publish, timing = self.ctx.publish_metric, self.ctx.record_timing
        self.ctx.publish_metric = lambda name, value: (self.published.append((name, value)), publish(name, value))[0]
        self.ctx.record_timing = lambda name, d, tags=None: (self.timings.append((name, d)), timing(name, d, tags))[0]
        self.ctx.flight_dump = lambda reason="", /, **fields: (self.dumps.append((reason, fields)), True)[1]
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def take(self) -> dict:
        box: dict = {}
        thread = threading.Thread(target=lambda: box.update(r=self.plugin.cmd_take_device({})), daemon=True)
        thread.start()
        thread.join(10.0)
        assert not thread.is_alive(), "take_device не вернулся за 10 с"
        return box["r"]

    def drive(self, seconds: float) -> None:
        """Вести `produce()` как процесс-источник: пауза 5 мс между вызовами."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.plugin.produce()
            time.sleep(0.005)

    def close(self) -> None:
        if getattr(self.plugin, "_session", None) is not None:
            self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(**kwargs) -> _Rig:
        rig = _Rig(monkeypatch, **kwargs)
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        rig.close()


def test_события_merge_не_больше_4_за_2_с_при_50_кадрах_в_секунду(make):
    # Период 0.012 с, не 0.02: фейк ставит срок кадра от «сейчас» после сна, и при 0.02 с на macOS выходит ~42 кадра/с
    # (замер: 84 кадра за 2 с). Нужно «не меньше 50 кадров/с», иначе порог frames >= 90 зависит от точности сна ОС.
    rig = make(port=make_port(frame_period_s=0.012))
    assert rig.take()["status"] == "ok"
    rig.drive(2.0)
    merges = len(rig.proxy.merges)
    frames = [value for name, value in rig.published if name == "frames"]
    assert merges <= 4, f"merge {merges} раз за 2 с: событие пишется не только при смене"
    assert frames, "publish_metric('frames') не вызывался"
    assert max(frames) >= 90, f"frames={max(frames)} за 2 с при 50 кадрах/с"
    assert all(path == TREE_PATH for path, _ in rig.proxy.merges)


def test_busy_один_инцидент_и_degraded(make, monkeypatch):
    monkeypatch.setattr(
        plugin_base, "_TICK_S", 0.0
    )  # каждый produce() — тик: повтор того же состояния не плодит инцидент
    rig = make(port=make_port(busy_for_s=60.0))
    result = rig.take()
    assert result["status"] == "error"
    assert result["device_state"] == "busy"
    rig.drive(0.1)
    assert len(rig.health.errors) == 1, f"report_error: {len(rig.health.errors)} раз"
    assert rig.health.degraded_reasons, "health.degraded не вызван"
    assert "busy" in rig.health.degraded_reasons[0]
    assert rig.plugin._reg.device_state == "busy"
    assert rig.proxy.merged("state")[-1] == "busy"


def test_on_stall_вызывает_flight_dump_owner_stall(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.plugin._on_stall("get_frame", 1.2)
    assert [reason for reason, _ in rig.dumps] == ["owner_stall"]
    assert len(rig.health.errors) == 1


def test_событие_device_ключи(make, monkeypatch):
    monkeypatch.setattr(fake_port, "FAKE_SERIAL", "SN1")
    rig = make(device_select="serial", device_serial="SN1")
    assert rig.take()["status"] == "ok"
    rig.drive(0.2)
    assert rig.proxy.merged("device")[-1] == {"kind": "serial", "value": "SN1", "name": ""}
    assert rig.proxy.merged("device_held")[-1] is True
    assert rig.proxy.merged("state")[-1] == "grabbing"
    assert rig.proxy.merged("profile")[-1] == "run"
    assert set(rig.proxy.merged("capabilities")[-1]) >= {"read_back", "live_write"}


def test_замеры_агрегируются_get_frame_не_на_каждый_кадр(make, monkeypatch):
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.2)
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.drive(1.0)
    names = [name for name, _ in rig.timings]
    frames = max(value for name, value in rig.published if name == "frames")
    assert frames >= 40
    assert 1 <= names.count("get_frame_ms") <= 6, f"get_frame_ms {names.count('get_frame_ms')} раз при {frames} кадрах"
    assert names.count("open_ms") == 1
    assert names.count("apply") >= 1
    assert all(0.0 <= value < 5.0 for name, value in rig.timings if name == "get_frame_ms"), "замер в секундах"


def test_настоящие_объекты_health_и_уровни(make, monkeypatch):
    """Настоящие `HealthState` и `PluginLevels`: инцидент busy доезжает до health, уровни — до хранилища."""
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)
    rig = make(port=make_port(busy_for_s=60.0), real=True)
    assert rig.take()["device_state"] == "busy"
    rig.drive(0.1)
    snap = get_or_create_health_state(rig.services).snapshot()
    assert snap["status"] == "degraded"
    assert snap["errors"] == 1
    assert "busy" in snap["degraded_reason"]
    published = rig.levels.publications()["camera_device"]
    assert set(published) >= LEVELS
    assert published["frames"] == 0
