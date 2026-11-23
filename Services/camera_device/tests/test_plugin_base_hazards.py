# -*- coding: utf-8 -*-
"""Хазард-тесты Task 2.3a (автор): гонки `take_device`, порядок `seq_id`, `set_cycle` при живом владельце,
повторный старт не подменяет план идущего цикла, отказ `build_plan` -> `status: error`, цвет и битый буфер.

Файл БЕЗ `from __future__ import annotations`: аннотации register-класса подкласса должны быть настоящими
объектами (`Annotated[..., FieldMeta]`). Всё, что может зависнуть, идёт в daemon-потоке с дедлайном.
Ожидаемые значения — литералы.
"""

import threading
import time
from typing import Annotated

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import Binding, PortError, RawFrame
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.testing.fake_port import FAKE_BINDINGS, make_port

CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}


def _bounded(fn, seconds: float = 10.0):
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"вызов не вернулся за {seconds} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


class _Rig:
    def __init__(self, monkeypatch, cfg: dict, port, plugin_cls=CameraDevicePlugin) -> None:
        self.port = port
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        services = MockProcessServices(name="cam_fake", config=cfg)
        self.wm = WorkerManager("test_cam")
        services.worker_manager = self.wm
        self.ctx = PluginContext(services=services, config=cfg, plugin_name=plugin_cls.name)
        self.plugin = plugin_cls()
        self.plugin.configure(self.ctx)

    def take(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_take_device({}))

    def close(self) -> None:
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def rig(monkeypatch):
    made: list[_Rig] = []

    def factory(cfg: dict | None = None, *, port=None, plugin_cls=CameraDevicePlugin) -> _Rig:
        item = _Rig(monkeypatch, {**CFG, **(cfg or {})}, port or make_port(frame_period_s=0.02), plugin_cls)
        made.append(item)
        return item

    yield factory
    for item in made:
        item.close()


def _names(port) -> list[str]:
    return [call[0] for call in port.calls]


def test_два_потока_take_device_дают_один_open(rig, monkeypatch):
    """Гонка двух `take_device`: один `open` в журнале, оба ответа `ok` (создание порта нарочно медленное)."""
    port = make_port(frame_period_s=0.02, open_delay_s=0.2)
    built = rig(port=port)

    def slow_create_port(driver: str):
        time.sleep(0.1)  # окно гонки на ленивом создании сеанса
        return port

    monkeypatch.setattr(plugin_base, "create_port", slow_create_port)
    barrier = threading.Barrier(2)
    answers: list[dict] = []

    def call() -> None:
        barrier.wait(5.0)
        answers.append(built.plugin.cmd_take_device({}))

    threads = [threading.Thread(target=call, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10.0)
        assert not thread.is_alive()
    assert [a["status"] for a in answers] == ["ok", "ok"]
    assert _names(built.port).count("open") == 1


def test_seq_id_строго_растёт_при_on_frame_и_produce_из_разных_потоков(rig):
    """`_on_frame` в одном потоке, `produce()` в другом: `seq_id` строго растёт, итог 500."""
    built = rig()
    plugin = built.plugin
    done = threading.Event()

    def feed() -> None:
        for number in range(1, 501):
            plugin._on_frame(RawFrame(bytearray(8), 4, 2, "mono8", number))
        done.set()

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    seen: list[int] = []
    deadline = time.monotonic() + 10.0
    while not done.is_set() and time.monotonic() < deadline:
        seen += [item["seq_id"] for item in plugin.produce()]
    feeder.join(10.0)
    assert done.is_set()
    seen += [item["seq_id"] for item in plugin.produce()]
    assert seen == sorted(set(seen)), "seq_id не строго растёт"
    assert seen[-1] == 500


def test_set_cycle_при_device_held_возвращает_False_и_не_меняет_цикл(rig):
    """Идущий цикл: `set_cycle` -> `False`, `_run`/`_ident` прежние; после остановки — `True` и замена."""
    built = rig()
    assert built.take()["status"] == "ok"
    session = built.plugin._session
    assert session.device_held
    run_before, ident_before = session._run, session._ident
    assert session.set_cycle(None, (), ()) is False
    assert (session._run, session._ident) == (run_before, ident_before)
    assert ident_before is not None and len(run_before) > 0

    assert built.plugin.cmd_release_device({})["status"] == "ok"
    assert not session.device_held
    assert session.set_cycle(None, (), ()) is True
    assert (session._run, session._ident) == ((), None)


def test_второй_take_device_при_grabbing_не_подменяет_план_идущего_цикла(rig):
    """Правка `exposure_time` посреди захвата: повторный `take_device` -> `ok`, в приборе всё ещё 10000.0."""
    built = rig()
    assert built.take()["status"] == "ok"
    run_before = built.plugin._session._run
    built.plugin._reg.exposure_time = 777.0
    assert built.take()["status"] == "ok"
    assert built.plugin._session.state == "grabbing"
    assert built.plugin._session._run == run_before
    assert built.plugin._session.params == {"exposure_time": 10000.0}
    written = [args for name, args, _ in built.port.calls if name == "set_param"]
    assert written == [("ExposureTime", 10000.0)]


class _ExtraRegisters(CameraDeviceRegisters):
    """Безусловное поле группы триггера без значения в плане rest: `build_plan` бросает ValueError."""

    trigger_extra: Annotated[int, FieldMeta("Лишний узел триггера")] = 1


class _BrokenPlanPlugin(CameraDevicePlugin):
    register_class = _ExtraRegisters

    def bindings(self):
        return {**FAKE_BINDINGS, "trigger_extra": Binding("genicam", "TriggerExtra", "int")}


def test_build_plan_бросает_take_device_отвечает_error_без_исключения(rig):
    """`ValueError` из плана -> `{"status": "error"}` с именем поля, прибор не открыт, исключения наружу нет."""
    built = rig(plugin_cls=_BrokenPlanPlugin)
    answer = built.take()
    assert answer["status"] == "error"
    assert "trigger_extra" in answer["error"]
    assert "open" not in _names(built.port)


@pytest.mark.parametrize(
    ("pixel_format", "size", "shape", "produced"),
    [
        pytest.param("rgb8", 24, (2, 4, 3), True, id="rgb8"),
        pytest.param("bgr8", 24, (2, 4, 3), True, id="bgr8"),
        pytest.param("mono8", 8, (2, 4), True, id="mono8"),
        pytest.param("rgb8", 8, None, False, id="rgb8_короткий_буфер"),
        pytest.param("mono16", 16, None, False, id="неизвестный_формат"),
    ],
)
def test_форма_кадра_по_pixel_format_битый_кадр_отбрасывается(rig, pixel_format, size, shape, produced):
    """Цвет — (h, w, 3); битый буфер/неизвестный формат: `produce()` не бросает, item нет, `frames` не растёт."""
    built = rig()
    plugin = built.plugin
    plugin._on_frame(RawFrame(bytearray(size), 4, 2, pixel_format, 1))
    items = plugin.produce()
    if produced:
        assert len(items) == 1
        assert items[0]["frame"].shape == shape
        assert plugin._frames == 1
    else:
        assert items == []
        assert plugin._frames == 0
        assert plugin._reg.frames == 0
        assert plugin.cmd_get_status({})["last_error"] != ""


def test_rest_selftrigger_пишет_период_run(rig):
    """`rest_trigger_source=SelfTrigger`: в покое пишется и период самотриггера из run (40), ошибки плана нет."""
    built = rig({"rest_managed": True, "rest_trigger_mode": "On", "rest_trigger_source": "SelfTrigger"})
    assert built.take()["status"] == "ok"
    assert built.plugin.cmd_release_device({})["status"] == "ok"
    names = _names(built.port)
    tail = built.port.calls[names.index("stop_grabbing") + 1 :]
    assert [args for name, args, _ in tail if name == "set_param"] == [
        ("TriggerMode", "On"),
        ("TriggerSource", "SelfTrigger"),
        ("TriggerSelfTriggerPeriod", 40),
    ]


def test_правка_device_serial_между_циклами_доходит_до_сеанса(rig):
    """Р12: `device_serial` правится после `release_device` -> следующий `take_device` ищет НОВЫЙ серийник."""
    built = rig()
    assert built.take()["status"] == "ok"
    assert built.plugin.cmd_release_device({})["status"] == "ok"
    built.plugin._reg.device_serial = "NOPE"
    assert built.take()["status"] == "error"
    assert built.plugin._session.state == "not_found"
    assert [call[:2] for call in built.port.calls if call[0] == "open"] == [("open", ("serial", "FAKE-0001"))]


@pytest.mark.parametrize(
    "error",
    [PortError("access", "make_port"), ImportError("dll"), OSError("x")],
    ids=["PortError", "ImportError", "OSError"],
)
def test_create_port_бросает_не_ValueError_take_device_отвечает_error(rig, error):
    """Хук вендора бросил не ValueError: `status: error`, исключения наружу нет, сеанс не создан."""

    class _Failing(CameraDevicePlugin):
        def create_port(self):
            raise error

    built = rig(plugin_cls=_Failing)
    answer = built.take()
    assert answer["status"] == "error"
    assert answer["error"] != ""
    assert built.plugin._session is None
