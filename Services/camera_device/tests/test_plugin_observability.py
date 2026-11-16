# -*- coding: utf-8 -*-
"""Наблюдаемость базы плагина камеры (Task 2.3b): метрики, событийное состояние, `health`, `flight_dump`.

Плагин настоящий, порт — фейк, `PluginContext` — настоящий над `MockProcessServices`. Подменены только приёмники:
`state_proxy` (счёт `merge`), `ctx.health` (фейк инцидентов), `publish_metric`/`record_timing`/`flight_dump`
(запись вызовов). Один тест (`test_настоящие_объекты`) идёт с настоящим `HealthState` и `PluginLevels`.
Ожидаемые числа — литералы из ACCEPTANCE задачи 2.3b. Вызовы, которые могут зависнуть, идут с дедлайном.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from multiprocess_framework.modules.process_module.heartbeat.telemetry import PluginLevels
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import RawFrame
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
        self.logs: list[tuple[str, str]] = []  # (уровень, текст): `ctx.log_*`, куда идёт мост логгера сеанса
        self.ctx.log_info = lambda msg, **kw: self.logs.append(("info", msg))
        self.ctx.log_warning = lambda msg, **kw: self.logs.append(("warning", msg))
        self.ctx.log_error = lambda msg, **kw: self.logs.append(("error", msg))
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


# --- Дополнение по ревью 2.3b (раунд 1) ---

# Прибор принимает запись, но читает 500 вместо 1000: узел `exposure_time` не подтверждён чтением -> `param_errors`.
_UNCONFIRMED = {"read_offset": {"ExposureTime": 500.0}, "exposure_time": 1000.0}
_SESSION_LOGGER = "camera_device.session"


def _bridges() -> list:
    return [h for h in logging.getLogger(_SESSION_LOGGER).handlers if isinstance(h, plugin_base._SessionLogBridge)]


def _unconfirmed_rig(make, **cfg) -> _Rig:
    rig = make(port=make_port(frame_period_s=0.02, read_offset=_UNCONFIRMED["read_offset"]), **cfg)
    assert rig.take()["status"] == "ok"
    return rig


def test_сверка_без_смен_не_даёт_merge(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.drive(0.1)
    before = len(rig.proxy.merges)
    for _ in range(20):
        rig.plugin._sync_events()
    assert len(rig.proxy.merges) - before == 0, "повторная сверка без смен снова пишет в дерево"
    assert rig.proxy.deletes == []


def test_ушедшие_ключи_словарей_снимаются_delete(make):
    rig = make(port=make_port(frame_period_s=0.02, read_offset={"ExposureTime": 500.0}), exposure_time=1000.0)
    assert rig.take()["status"] == "ok"
    rig.drive(0.1)
    assert set(rig.plugin._published["param_errors"]) == {"exposure_time"}
    shrunk = dict(rig.plugin._published, params={}, params_status={}, param_errors={})
    rig.plugin._publish_events(shrunk)
    assert sorted(rig.proxy.deletes) == [
        f"{TREE_PATH}.param_errors.exposure_time",
        f"{TREE_PATH}.params.exposure_time",
        f"{TREE_PATH}.params_status.exposure_time",
    ]


def test_новый_ключ_param_errors_один_инцидент_param(make):
    rig = _unconfirmed_rig(make, exposure_time=1000.0)
    rig.drive(0.1)
    for _ in range(5):
        rig.plugin._sync_events()
    param = [(exc, ctx) for exc, ctx in rig.health.errors if ctx == "camera_device.param"]
    assert len(param) == 1, f"инцидентов param: {len(param)}"
    assert str(param[0][0]) == "exposure_time: не подтвердилось чтением"
    assert len(rig.health.errors) == 1, "состояние grabbing не должно давать инцидентов сеанса"


def test_тик_сверяет_события_без_on_state(make, monkeypatch):
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.drive(0.1)
    # `last_error` меняется без смены состояния (например, отказ закрытия узла): `on_state` не зовётся, только окно
    rig.plugin._session._last_error = "PortError kind=other: x"
    rig.drive(0.05)
    assert rig.proxy.merged("last_error")[-1] == "PortError kind=other: x"


def test_мост_логгера_доводит_строки_сеанса_до_ctx_и_снимается(make):
    rig = make()
    assert len(_bridges()) == 0
    assert rig.take()["status"] == "ok"
    assert len(_bridges()) == 1
    lines = [text for level, text in rig.logs if level == "info"]
    assert any(text.startswith("session state=opening->grabbing") for text in lines), lines
    rig.plugin.shutdown(rig.ctx)
    assert _bridges() == []
    count = len(rig.logs)
    logging.getLogger(_SESSION_LOGGER).warning("после shutdown")
    assert len(rig.logs) == count, "снятый мост всё ещё пишет в ctx"


def test_мост_снимается_даже_если_release_бросил(make):
    rig = make()
    assert rig.take()["status"] == "ok"

    def boom(data):
        raise RuntimeError("release")

    with pytest.MonkeyPatch.context() as local:
        local.setattr(rig.plugin, "cmd_release_device", boom)
        with pytest.raises(RuntimeError):
            rig.plugin.shutdown(rig.ctx)
    assert _bridges() == []
    rig.plugin._attach_log_bridge()
    rig.plugin._attach_log_bridge()  # второй вызов моста не вешает
    assert len(_bridges()) == 1


def test_битый_кадр_виден_в_dropped_и_уровни_несут_значения(make, monkeypatch):
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)
    rig = make()
    rig.plugin._on_frame(RawFrame(data=bytearray(3), width=2, height=2, pixel_format="rgb8", frame_num=1, extras={}))
    rig.plugin.produce()  # битый кадр отброшен: длина буфера 3, нужно 12
    rig.plugin.produce()  # тик публикует dropped
    last = {name: value for name, value in rig.published}
    assert last["dropped"] == 1
    assert last["frames"] == 0
    assert last["errors"] == 0
    assert last["pending"] == 0
    assert last["param_errors_count"] == 0


def test_уровни_errors_param_errors_count_fps_со_значениями(make, monkeypatch):
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.2)
    rig = _unconfirmed_rig(make, exposure_time=1000.0)
    rig.drive(0.8)
    last = {name: value for name, value in rig.published}
    assert last["errors"] == 1  # один узел не подтверждён чтением
    assert last["param_errors_count"] == 1
    assert last["fps"] > 10, f"fps={last['fps']}"
    assert last["dropped"] == 0


def test_профиль_при_отказе_открытия_не_rest_а_при_штатном_закрытии_rest(make):
    busy = make(port=make_port(busy_for_s=60.0))
    assert busy.take()["device_state"] == "busy"
    busy.plugin.cmd_release_device({})
    assert busy.proxy.merged("state")[-1] == "closed"
    assert busy.proxy.merged("profile")[-1] is None, "rest в прибор не писался"
    good = make()
    assert good.take()["status"] == "ok"
    assert good.proxy.merged("profile")[-1] == "run"
    good.plugin.cmd_release_device({})
    assert good.proxy.merged("profile")[-1] == "rest"


def test_настоящий_StateProxy_ушедший_ключ_снят_из_дерева(make):
    store = TreeStore()

    class Router:
        def send_async(self, msg, priority="normal"):
            data = msg["data"]
            if msg["command"] == "state.merge":
                store.merge(data["path"], data["data"])
            elif msg["command"] == "state.delete":
                store.delete(data["path"])

    rig = make(trigger_managed=True, trigger_mode="On", trigger_source="Software")
    rig.ctx.state_proxy = StateProxy(PROCESS_NAME, router=Router())
    assert rig.take()["status"] == "ok"
    rig.drive(0.1)
    node = store.get(TREE_PATH)
    assert node["state"] == "grabbing"
    assert node["params"] == rig.plugin._session.params
    keys = sorted(node["params"])
    assert len(keys) >= 2, keys
    kept = {keys[0]: node["params"][keys[0]]}
    rig.plugin._publish_events(dict(rig.plugin._published, params=kept, params_status={}))
    node = store.get(TREE_PATH)
    assert node["params"] == kept
    assert node["params_status"] == {}


def _until(condition, seconds: float = 3.0) -> bool:
    """Ждать условие с дедлайном (без `sleep` наугад)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def test_degraded_снимается_при_выходе_из_отказа_чужая_заявка_остаётся(make):
    rig = make(port=make_port(busy_for_s=60.0), real=True)
    health = get_or_create_health_state(rig.services)
    assert rig.take()["device_state"] == "busy"
    assert health.snapshot()["status"] == "degraded"
    rig.plugin.cmd_release_device({})
    assert _until(lambda: health.snapshot()["status"] == "ok"), health.snapshot()
    # чужая заявка переживает выход из отказа: свой `set_status("ok")` снимает только свою
    health.degraded("other down", owner="other_plugin")
    assert rig.take()["device_state"] == "busy"
    assert health.snapshot()["status"] == "degraded"
    rig.plugin.cmd_release_device({})
    assert _until(lambda: rig.plugin._seen_state == "closed")
    with rig.plugin._events_lock:  # сверка закончена: `set_status` вызывается в ней же
        pass
    snap = health.snapshot()
    assert snap["status"] == "degraded"
    assert "other down" in snap["degraded_reason"], snap


def test_device_held_в_дереве_снимается_быстрее_окна_после_отказа(make, monkeypatch):
    monkeypatch.setattr(plugin_base, "_TICK_S", 5.0)  # окно заведомо больше срока теста: снимает не оно
    rig = make(port=make_port(busy_for_s=60.0))
    assert rig.take()["device_state"] == "busy"
    assert True in rig.proxy.merged("device_held"), (
        "на отказе в дерево ушло device_held=True (on_state до снятия флага)"
    )
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.3 and rig.proxy.merged("device_held")[-1] is not False:
        rig.plugin.produce()
        time.sleep(0.005)
    assert rig.proxy.merged("device_held")[-1] is False, "device_held завис в дереве до окна"
    assert rig.plugin._session.device_held is False
    before = len(rig.proxy.merges)
    for _ in range(20):
        rig.plugin.produce()
    assert len(rig.proxy.merges) == before, "проверка device_held пишет в дерево без смены"
