# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 4.2a: плагин `HikvisionCameraPlugin` «на ядре» `CameraDevicePlugin`.

Написаны ДО кода плагина по критериям приёмки и по готовым интерфейсам (`Services/camera_device/*`,
`driver.py`, фейк MVS-камеры из `conftest.py`). Реализацию плагина (`plugin/plugin.py`, `plugin/registers.py`)
автор не читал. Проверяется наблюдаемое: item из `produce()`, журналы фейк-порта и фейк-камеры, ответы
команд, поля register'а. Ожидаемые значения — литералы из критериев приёмки.

Что собрано настоящим: плагин + `RegistersManager` + `PluginOrchestrator` (обработчик `register_update`) +
настоящие `DeviceSession`/`WorkerManager` + настоящий драйвер `mvs` (`driver.make_port`) над фейковым `MvCamera`.
Фейки: `MvCamera` (журнал `MV_CC_*`), `FakePort` ядра (там, где нужны capability `restart_regrab` и
`open_delay_s`) и менеджер процесса (`MockProcessServices`).
Кадры в плагин подаются мимо порта: `plugin._on_frame(RawFrame(...))`, затем `produce()`; один тест гонит кадр
через настоящий порт. Всё, что может зависнуть, идёт в daemon-потоке с дедлайном (`_bounded`).

Размер вывода: в тестах цвета задан `resolution_width/height`, равный размеру кадра: тогда ресайз — no-op при любом
правиле «когда ресайзить» (умолчание register'а 1440x1080 не равно размеру тестовых кадров 4x2 и 6x6).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.interface import RawFrame
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.testing.fake_port import ALL_CAPABILITIES, FAKE_BINDINGS, make_port
from Services.hikvision_camera import driver
from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin
from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters
from Services.hikvision_camera.sdk import bindings as sdk_bindings
from Services.hikvision_camera.sdk.constants import PixelType
from Services.hikvision_camera.sdk.errors import MV_E_NODATA
from Services.hikvision_camera.tests.conftest import make_fake_cam_cls

pytestmark = pytest.mark.timeout(60)

PROCESS_NAME = "cam_hik"
SOURCE_FILE = Path(__file__).resolve().parents[1] / "plugin" / "plugin.py"
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


# ---------------------------------------------------------------------------------------------- #
# 1. Цвет: плагин отдаёт потребителям BGR
# ---------------------------------------------------------------------------------------------- #


def test_rgb8_отдаётся_как_bgr_с_переставленными_каналами(make):
    rig = make(_res(4, 2))
    items = _feed(rig.plugin, RGB_24, 4, 2, "rgb8")
    assert len(items) == 1
    frame = items[0]["frame"]
    assert frame.shape == (2, 4, 3)
    assert frame[0, 0].tolist() == [2, 1, 0]
    assert frame[1, 3].tolist() == [23, 22, 21]


def test_rgb8_метаданные_item(make):
    rig = make(_res(4, 2))
    item = _feed(rig.plugin, RGB_24, 4, 2, "rgb8")[0]
    assert item["pixel_format"] == "bgr8"
    assert item["source_format"] == "rgb8"
    assert item["frame"].flags.c_contiguous
    assert rig.plugin._frames == 1


def test_bgr8_проходит_без_перестановки(make):
    rig = make(_res(4, 2))
    item = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]
    assert item["frame"].shape == (2, 4, 3)
    assert item["frame"][0, 0].tolist() == [0, 1, 2]
    assert item["pixel_format"] == "bgr8"
    assert item["source_format"] == "bgr8"


def test_mono8_растягивается_в_три_одинаковых_канала(make):
    rig = make(_res(4, 2))
    item = _feed(rig.plugin, bytes(range(8)), 4, 2, "mono8")[0]
    assert item["frame"].shape == (2, 4, 3)
    assert item["frame"][1, 3].tolist() == [7, 7, 7]


# ---------------------------------------------------------------------------------------------- #
# 2. Дебайер: цвет по GenICam-паттерну (имена кодов OpenCV инвертированы — решает цвет сцены, не имя)
# ---------------------------------------------------------------------------------------------- #

# паттерн -> (строка, столбец) красного пикселя в мозаике 2x2 по GenICam (литерал из критериев приёмки)
RED_AT = {
    "bayer_rg8": (0, 0),
    "bayer_bg8": (1, 1),
    "bayer_gr8": (0, 1),
    "bayer_gb8": (1, 0),
}


@pytest.mark.parametrize("pixel_format", sorted(RED_AT))
def test_красная_сцена_bayer8_даёт_красный_bgr(make, pixel_format):
    row, col = RED_AT[pixel_format]
    mosaic = np.zeros((6, 6), dtype=np.uint8)
    mosaic[row::2, col::2] = 255
    rig = make(_res(6, 6))
    items = _feed(rig.plugin, mosaic.tobytes(), 6, 6, pixel_format)
    assert len(items) == 1
    frame = items[0]["frame"]
    assert frame.shape == (6, 6, 3)
    assert items[0]["pixel_format"] == "bgr8"
    interior = frame[2:4, 2:4].astype(int)
    np.testing.assert_allclose(interior, np.tile([0, 0, 255], (2, 2, 1)), atol=1)


def test_bayer_rg8_пиксель_2_2_красный_по_эталону_критериев(make):
    mosaic = np.zeros((6, 6), dtype=np.uint8)
    mosaic[0::2, 0::2] = 255
    rig = make(_res(6, 6))
    frame = _feed(rig.plugin, mosaic.tobytes(), 6, 6, "bayer_rg8")[0]["frame"]
    np.testing.assert_allclose(frame[2, 2].astype(int), [0, 0, 255], atol=1)


# ---------------------------------------------------------------------------------------------- #
# 3. Отброс неподдерживаемого / битого кадра
# ---------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("pixel_format", "width", "height", "size"),
    [
        pytest.param("bayer_rg10", 6, 6, 36, id="bayer_rg10_буфер_36"),
        pytest.param("bayer_rg10", 6, 6, 72, id="bayer_rg10_буфер_72"),
        pytest.param("mono16", 4, 2, 16, id="mono16"),
    ],
)
def test_неподдерживаемый_формат_отбрасывается_без_исключения(make, pixel_format, width, height, size):
    rig = make(_res(width, height))
    plugin = rig.plugin
    errors_before = get_or_create_health_state(rig.services).snapshot()["errors"]
    items = _feed(plugin, bytes(size), width, height, pixel_format)
    assert items == []
    assert plugin._dropped == 1
    assert plugin._frames == 0
    last_error = plugin.cmd_get_status({})["last_error"]
    assert isinstance(last_error, str)
    assert last_error != ""
    assert get_or_create_health_state(rig.services).snapshot()["errors"] == errors_before


# ---------------------------------------------------------------------------------------------- #
# 4. Команды: ровно девять, старые тринадцать ушли, subprocess в плагине нет
# ---------------------------------------------------------------------------------------------- #

NEW_COMMANDS = {
    "take_device",
    "release_device",
    "get_status",
    "reset_stats",
    "read_params",
    "apply_params",
    "list_devices",
    "describe_params",
    "trigger_software",
}
OLD_COMMANDS = (
    "open",
    "close",
    "start_capture",
    "stop_capture",
    "enum_devices",
    "get_parameters",
    "set_parameters",
    "set_exposure",
    "set_gain",
    "set_frame_rate",
    "set_resolution",
    "open_sdk_app",
    "close_sdk_app",
)


def test_плагин_наследует_ядро_и_называется_hikvision():
    assert issubclass(HikvisionCameraPlugin, CameraDevicePlugin)
    assert HikvisionCameraPlugin.name == "hikvision"


def test_register_плагина_наследует_register_ядра():
    assert issubclass(HikvisionCameraRegisters, CameraDeviceRegisters)


def test_команды_плагина_ровно_девять_имён_ядра():
    assert set(HikvisionCameraPlugin.commands) == NEW_COMMANDS


@pytest.mark.parametrize("old", OLD_COMMANDS)
def test_старая_команда_отсутствует(old):
    assert old not in HikvisionCameraPlugin.commands


def test_в_исходнике_плагина_нет_subprocess():
    assert "subprocess" not in SOURCE_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------- #
# 5. Порядок записи плана run (настоящий драйвер mvs над фейк-камерой)
# ---------------------------------------------------------------------------------------------- #


def test_порядок_записи_open_auto_exposure_readback_start(make):
    cam = _gated_cam()
    rig = make({"exposure_time": 5000}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    i_open = _pos(log, ("MV_CC_OpenDevice", ()))
    i_auto = _pos(log, ("MV_CC_SetEnumValueByString", ("ExposureAuto", "Off")))
    i_set = _pos(log, ("MV_CC_SetFloatValue", ("ExposureTime", 5000.0)))
    i_get = _pos(log, ("MV_CC_GetFloatValue", ("ExposureTime",)), after=i_set)
    i_start = _pos(log, ("MV_CC_StartGrabbing", ()))
    assert i_open < i_auto < i_set < i_get < i_start
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_frame_rate_enable_true_пишется_раньше_frame_rate(make):
    cam = _gated_cam()
    rig = make({"frame_rate_enable": True}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    i_enable = _pos(log, ("MV_CC_SetBoolValue", ("AcquisitionFrameRateEnable", True)))
    i_rate = _pos(log, ("MV_CC_SetFloatValue", ("AcquisitionFrameRate", 25.0)))
    assert i_enable < i_rate
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_frame_rate_enable_false_frame_rate_не_пишется(make):
    cam = _gated_cam()
    rig = make({"frame_rate_enable": False}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    assert [entry for entry in log if entry[0] == "MV_CC_SetFloatValue" and entry[1][0] == "AcquisitionFrameRate"] == []
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_packet_managed_false_пакетные_узлы_не_пишутся(make):
    cam = _gated_cam()
    rig = make({"packet_managed": False}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    written = [entry[1][0] for entry in _quiet(cam) if entry[0] == "MV_CC_SetIntValue"]
    assert "GevSCPSPacketSize" not in written
    assert "GevSCPD" not in written


def test_packet_managed_true_пишет_размер_и_задержку_пакета(make):
    cam = _gated_cam()
    rig = make({"packet_managed": True}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    _pos(log, ("MV_CC_SetIntValue", ("GevSCPSPacketSize", 1500)))
    _pos(log, ("MV_CC_SetIntValue", ("GevSCPD", 0)))
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


# ---------------------------------------------------------------------------------------------- #
# 6. Правка при захвате (register_update в состоянии grabbing)
# ---------------------------------------------------------------------------------------------- #


def _port_names(port) -> list[str]:
    return [call[0] for call in list(port.calls)]


def test_правка_экспозиции_при_захвате_с_restart_regrab_stop_set_get_start(make):
    port = make_port(frame_period_s=0.02)
    assert "restart_regrab" in port.capabilities
    rig = make(FAKE_PORT_CFG, port=port, bindings=FAKE_BINDINGS)
    assert rig.take()["status"] == "ok"
    base = len(port.calls)

    result = rig.register_update("exposure_time", 6000)

    assert result["success"] is True, result
    _wait(lambda: _port_names(port)[base:].count("start_grabbing") == 1, "перезахват: start_grabbing после правки")
    after = [(name, args) for name, args, _ in port.calls[base:] if name != "get_frame"]
    assert after == [
        ("stop_grabbing", ()),
        ("set_param", ("ExposureTime", 6000.0)),
        ("get_param", ("ExposureTime",)),
        ("start_grabbing", ()),
    ]
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_правка_gain_при_захвате_на_mvs_stop_close_open_весь_план_start(make):
    cam = _gated_cam()
    rig = make(cam_cls=cam)
    assert rig.take()["status"] == "ok"
    base = len(_quiet(cam))

    result = rig.register_update("gain", 6.0)

    assert result["success"] is True, result
    _wait(lambda: ("MV_CC_StartGrabbing", ()) in _quiet(cam)[base:], "перезахват: StartGrabbing после правки")
    window = _quiet(cam)[base:]
    assert window[0] == ("MV_CC_StopGrabbing", ())
    assert window[-1] == ("MV_CC_StartGrabbing", ())
    i_stop = _pos(window, ("MV_CC_StopGrabbing", ()))
    i_close = _pos(window, ("MV_CC_CloseDevice", ()), after=i_stop)
    i_open = _pos(window, ("MV_CC_OpenDevice", ()), after=i_close)
    i_gain = _pos(window, ("MV_CC_SetFloatValue", ("Gain", 6.0)), after=i_open)
    # план записи пишется целиком (не только Gain): ExposureTime идёт в том же окне
    i_exposure = _pos(window, ("MV_CC_SetFloatValue", ("ExposureTime", 10000.0)), after=i_open)
    assert i_gain < len(window) - 1
    assert i_exposure < len(window) - 1
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


# ---------------------------------------------------------------------------------------------- #
# 7. Item после 130 кадров
# ---------------------------------------------------------------------------------------------- #


def test_item_после_130_кадров_номера_не_сворачиваются_и_поля_полны(make):
    cam = _gated_cam()  # шлюз закрыт: сеанс сам кадров не отдаёт, их подаёт тест
    rig = make(_res(4, 2), cam_cls=cam)
    assert rig.take()["status"] == "ok"
    plugin = rig.plugin
    items = []
    for number in range(1, 131):
        got = _feed(plugin, RGB_24, 4, 2, "bgr8", number)
        assert len(got) == 1
        items.append(got[0])

    assert [item["seq_id"] for item in items] == list(range(1, 131))
    last = items[-1]
    assert last["seq_id"] == 130
    assert last["frame_id"] == 130
    assert last["device_frame_num"] == 130
    assert last["camera_id"] == 3
    assert last["device_id"] == "SN1"
    assert isinstance(last["timestamp"], float)
    assert abs(last["ts"] - time.time()) < 5
    required = {
        "frame",
        "camera_id",
        "device_id",
        "seq_id",
        "frame_id",
        "timestamp",
        "ts",
        "pixel_format",
        "source_format",
    }
    assert required <= set(last)


def test_кадр_через_настоящий_порт_доходит_как_bgr_item(make):
    """Плагин + сеанс + драйвер mvs + фейк-камера целиком: rgb8 из `GetImageBuffer` -> item в BGR."""
    cam = _gated_cam(pixel_type=PixelType.RGB8, data=RGB_24, width=4, height=2)
    rig = make(_res(4, 2), cam_cls=cam)
    assert rig.take()["status"] == "ok"
    cam.gate.release()
    items: list[dict] = []
    _wait(lambda: items.extend(rig.plugin.produce()) or bool(items), "item из настоящего порта")
    item = items[0]
    assert item["frame"].shape == (2, 4, 3)
    assert item["frame"][0, 0].tolist() == [2, 1, 0]
    assert item["source_format"] == "rgb8"
    assert item["device_frame_num"] == 1
    assert item["device_id"] == "SN1"


# ---------------------------------------------------------------------------------------------- #
# 8. produce() не блокируется во время перезахвата
# ---------------------------------------------------------------------------------------------- #


def test_produce_не_блокируется_на_перезахвате_с_закрытием_порта(make):
    port = make_port(capabilities=ALL_CAPABILITIES - {"restart_regrab"}, open_delay_s=0.5, frame_period_s=0.02)
    rig = make(FAKE_PORT_CFG, port=port, bindings=FAKE_BINDINGS)
    assert rig.take()["status"] == "ok"
    editor = threading.Thread(target=lambda: rig.register_update("exposure_time", 6000.0), daemon=True)
    editor.start()
    _wait(lambda: _port_names(port).count("open") == 2, "перезахват дошёл до второго open")

    durations = []
    for _ in range(100):
        started = time.perf_counter()
        rig.plugin.produce()
        durations.append(time.perf_counter() - started)
    regrab_still_running = _port_names(port).count("start_grabbing") == 1

    editor.join(10.0)
    assert not editor.is_alive()
    _wait(lambda: _port_names(port).count("start_grabbing") == 2, "перезахват завершился")
    assert regrab_still_running, "перезахват кончился раньше замеров: тест ничего не доказывает"
    assert max(durations) < 0.05


# ---------------------------------------------------------------------------------------------- #
# 9. Умолчания и согласованность таблицы привязки с register'ом
# ---------------------------------------------------------------------------------------------- #


def test_take_device_без_правок_register_параметры_пишутся_без_ошибок(make):
    cam = _gated_cam()
    rig = make(cam_cls=cam)
    answer = rig.take()
    assert answer["status"] == "ok", answer
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_ключи_таблицы_привязки_драйвера_есть_в_полях_register():
    assert set(driver.BINDINGS) <= set(HikvisionCameraRegisters.model_fields)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("gain", 0.0, id="gain"),
        pytest.param("frame_rate", 25.0, id="frame_rate"),
        pytest.param("exposure_time", 10000.0, id="exposure_time"),
        pytest.param("packet_size", 1500, id="packet_size"),
        pytest.param("packet_delay", 0, id="packet_delay"),
        pytest.param("packet_managed", False, id="packet_managed"),
        pytest.param("frame_rate_enable", False, id="frame_rate_enable"),
        pytest.param("exposure_auto", "Off", id="exposure_auto"),
        pytest.param("resolution_width", 1440, id="resolution_width"),
        pytest.param("resolution_height", 1080, id="resolution_height"),
        pytest.param("resize_mode", "letterbox", id="resize_mode"),
    ],
)
def test_умолчание_поля_register(field, expected):
    assert field in HikvisionCameraRegisters.model_fields
    value = getattr(HikvisionCameraRegisters(), field)
    assert value == expected
    assert type(value) is type(expected)


def test_exposure_time_вендорского_register_применяется_перезапуском():
    meta = HikvisionCameraRegisters.get_all_fields_meta()["exposure_time"]
    assert meta.apply == "restart"


def test_exposure_auto_есть_в_базовом_register_ядра_перед_exposure_time():
    fields = list(CameraDeviceRegisters.model_fields)
    assert "exposure_auto" in fields
    assert fields.index("exposure_auto") < fields.index("exposure_time")


def test_exposure_auto_во_вендорском_register_перед_exposure_time():
    fields = list(HikvisionCameraRegisters.model_fields)
    assert "exposure_auto" in fields
    assert fields.index("exposure_auto") < fields.index("exposure_time")


@pytest.mark.parametrize("value", ["Off", "Once", "Continuous"])
def test_exposure_auto_принимает_три_значения(value):
    assert CameraDeviceRegisters(exposure_auto=value).exposure_auto == value


def test_exposure_auto_отвергает_чужое_значение():
    assert "exposure_auto" in CameraDeviceRegisters.model_fields
    with pytest.raises(ValidationError):
        CameraDeviceRegisters(exposure_auto="Bogus")


# ---------------------------------------------------------------------------------------------- #
# 10. Выход и ресайз
# ---------------------------------------------------------------------------------------------- #


def test_выход_плагина_один_порт_frame_image_bgr():
    outputs = HikvisionCameraPlugin.outputs
    assert [(p.name, p.dtype, p.shape) for p in outputs] == [("frame", "image/bgr", "(H, W, 3)")]
    assert all(isinstance(p, Port) for p in outputs)


def test_letterbox_4x2_в_8x4_без_полей(make):
    rig = make({**_res(8, 4), "resize_mode": "letterbox"})
    frame = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]["frame"]
    assert frame.shape == (4, 8, 3)


def test_letterbox_4x2_в_4x4_чёрные_поля_сверху_и_снизу(make):
    rig = make({**_res(4, 4), "resize_mode": "letterbox"})
    frame = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]["frame"]
    assert frame.shape == (4, 4, 3)
    assert int(frame[0].sum()) == 0
    assert int(frame[1].sum()) == 66
    assert int(frame[3].sum()) == 0


def test_stretch_4x2_в_4x4_верхняя_строка_не_чёрная(make):
    rig = make({**_res(4, 4), "resize_mode": "stretch"})
    frame = _feed(rig.plugin, RGB_24, 4, 2, "bgr8")[0]["frame"]
    assert frame.shape == (4, 4, 3)
    assert int(frame[0].sum()) > 0


def test_resolution_width_ноль_отвергается_конструктором_register():
    assert "resolution_width" in HikvisionCameraRegisters.model_fields
    with pytest.raises(ValidationError):
        HikvisionCameraRegisters(resolution_width=0)


def test_resolution_width_ноль_отвергается_менеджером_register_а_один_принимается():
    assert "resolution_width" in HikvisionCameraRegisters.model_fields
    name = HikvisionCameraPlugin.name
    manager = RegistersManager(registers={name: HikvisionCameraRegisters()})
    ok_one, _ = manager.set_field_value(name, "resolution_width", 1)
    ok_zero, _ = manager.set_field_value(name, "resolution_width", 0)
    assert ok_one is True
    assert ok_zero is False
