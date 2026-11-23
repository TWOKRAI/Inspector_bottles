# -*- coding: utf-8 -*-
"""Общий каркас слепых тестов Task 4.2a (`test_plugin_on_core*.py`): настоящий плагин + `RegistersManager` +
`PluginOrchestrator`, фейк-камера со шлюзом кадров, ограниченный по времени вызов, чтение журнала фейк-камеры.

Не набор тестов (имя не `test_*`, не собирается); `make` — фикстура pytest, её подключают импортом.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.interface import RawFrame
from Services.hikvision_camera import driver
from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin
from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters
from Services.hikvision_camera.sdk import bindings as sdk_bindings
from Services.hikvision_camera.sdk.errors import MV_E_NODATA
from Services.hikvision_camera.tests.conftest import make_fake_cam_cls

PROCESS_NAME = "cam_hik"
BASE_CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "SN1"}
FAKE_PORT_CFG = {"device_serial": "FAKE-0001"}  # серийный номер FakePort ядра
RGB_24 = bytes(range(24))
# Шум журнала фейк-камеры: владелец сеанса непрерывно зовёт GetImageBuffer (даже без кадров).
CAM_NOISE = frozenset({"MV_CC_GetImageBuffer", "MV_CC_FreeImageBuffer"})


# ---------------------------------------------------------------------------------------------- #
# Каркас
# ---------------------------------------------------------------------------------------------- #


def _bounded(fn, seconds: float = 10.0):
    """Вызов в daemon-потоке с дедлайном: зависший плагин не вешает набор; исключение вызова пробрасывается."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста как есть
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"вызов не вернулся за {seconds} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


def _wait(predicate, what: str, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail(f"за {timeout} с не случилось: {what}")


def _gated_cam(**kwargs):
    """Фейк `MvCamera`, у которого кадр выдаётся только по `cls.gate.release()`; иначе таймаут (`None` у порта).

    Без шлюза владелец сеанса крутил бы `GetImageBuffer` без пауз (фейк отвечает мгновенно); шлюз даёт 20 мс паузы
    и детерминированное число кадров: нужный тесту, ни одного лишнего.
    """
    base = make_fake_cam_cls(**kwargs)
    gate = threading.Semaphore(0)

    class GatedCam(base):
        def MV_CC_GetImageBuffer(self, stFrame, nMsec):  # noqa: N802 — имя SDK
            if not gate.acquire(timeout=0.02):
                self._journal("MV_CC_GetImageBuffer", (nMsec,))
                return MV_E_NODATA
            return super().MV_CC_GetImageBuffer(stFrame, nMsec)

    GatedCam.gate = gate
    return GatedCam


def _quiet(cam_cls) -> list[tuple]:
    """Журнал фейк-камеры без шума и без id потока: `[(имя, args), ...]`."""
    return [(name, args) for name, args, _ in list(cam_cls.journal) if name not in CAM_NOISE]


def _pos(log: list[tuple], entry: tuple, after: int = -1) -> int:
    """Индекс первой записи `entry` после индекса `after`; отсутствие — отказ теста с журналом в тексте."""
    for index in range(after + 1, len(log)):
        if log[index] == entry:
            return index
    pytest.fail(f"нет записи {entry} после позиции {after} в журнале: {log}")


class _Rig:
    """Настоящий плагин + `RegistersManager` + `PluginOrchestrator`; порт — фейк ядра или `mvs` над фейк-камерой."""

    def __init__(self, monkeypatch, cfg: dict | None, *, port=None, bindings=None, cam_cls=None) -> None:
        cfg = {**BASE_CFG, **(cfg or {})}
        self.port, self.cam_cls = port, cam_cls
        if cam_cls is not None:
            # плагин берёт порт у `driver.make_port()`: подменяем класс камеры и признак «SDK есть»
            monkeypatch.setattr(driver, "MvCamera", cam_cls)
            monkeypatch.setattr(sdk_bindings, "SDK_AVAILABLE", True)
        self.plugin = HikvisionCameraPlugin()
        if port is not None:
            self.plugin.create_port = lambda: port  # хук ядра `create_port(self)`
        if bindings is not None:
            self.plugin.bindings = lambda: bindings  # хук ядра `bindings(self)`: до `configure` (подписка на поля)
        self.name = HikvisionCameraPlugin.name
        self.services = MockProcessServices(name=PROCESS_NAME, config=cfg)
        self.wm = WorkerManager("test_hik")
        self.services.worker_manager = self.wm
        self.rm = RegistersManager(registers={self.name: HikvisionCameraRegisters()})
        self.ctx = PluginContext(services=self.services, config=cfg, registers=self.rm, plugin_name=self.name)
        self.orch = PluginOrchestrator(self.services)
        self.orch._registers_manager = self.rm
        self.plugin.configure(self.ctx)

    def take(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_take_device({}))

    def register_update(self, field: str, value) -> dict:
        """`register_update` как из системного потока процесса: отдельный поток, результат обработчика."""
        box: dict = {}

        def system_thread() -> None:
            box["result"] = self.orch._on_register_update(
                {"data": {"register": self.name, "field": field, "value": value}}
            )

        thread = threading.Thread(target=system_thread, name="system_sim", daemon=True)
        thread.start()
        thread.join(10.0)
        assert not thread.is_alive(), "обработчик register_update не вернулся за 10 с"
        return box["result"]

    def close(self) -> None:
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(cfg: dict | None = None, **kwargs) -> _Rig:
        rig = _Rig(monkeypatch, cfg, **kwargs)
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        rig.close()


def _feed(plugin, data: bytes, width: int, height: int, pixel_format: str, number: int = 1) -> list[dict]:
    """Кадр в обход порта: `_on_frame` -> `produce()`."""
    plugin._on_frame(RawFrame(bytearray(data), width, height, pixel_format, number))
    return plugin.produce()


def _res(width: int, height: int) -> dict:
    return {"resolution_width": width, "resolution_height": height}
