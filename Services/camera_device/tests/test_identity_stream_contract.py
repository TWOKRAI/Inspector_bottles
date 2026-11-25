# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты W1-a: личность прибора, выбор записи по подсети, здоровье потока.

Purpose: закрепить до кода контракт `DeviceInfo` / `entry_text` / `select_device` / `AmbiguousDeviceError`,
счётчики потока `RawFrame.lost_packets` / `trigger_index`, события `identity` и `stream`, строки лога плагина и
жизненный цикл `port.device_info` у фейка. Новые имена импортируются ВНУТРИ теста: до кода тест падает по
поведению, а не на сборе файла.

Стенд плагина: настоящие `CameraDevicePlugin`, `PluginContext` над `MockProcessServices`, настоящий `WorkerManager`;
подменён только `plugin_base.create_port` (порт — фейк) и приёмники `state_proxy` (запись `merge`) и
`publish_metric` (запись уровней). Строки лога читаются из журнала `MockProcessServices.logs`. Ожидаемые значения
- литералы из ACCEPTANCE задачи W1-a. Вызов, который может зависнуть, идёт в daemon-потоке с `join(timeout)`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import make_port

__all__ = []

PROCESS_NAME = "cam_identity"
SERIAL = "DA1689923"
PREFIX = "CameraDevicePlugin:"
DEADLINE_S = 10.0

# Тексты записей перечисления (`entry_text`): ip / mask / host_ip / mac. Литералы, не вычисляются из кода.
E_A = "ip=192.168.1.20 mask=255.255.255.0 host_ip=169.254.49.100 mac=00:11:1c:f6:a2:3b"
E_B = "ip=192.168.1.20 mask=255.255.255.0 host_ip=192.168.1.100 mac=00:11:1c:f6:a2:3b"
E_B2 = "ip=192.168.1.20 mask=255.255.255.0 host_ip=192.168.1.101 mac=00:11:1c:f6:a2:3b"
E_D = "ip=192.168.1.20 mask=255.255.255.0 host_ip=10.0.0.5 mac=00:11:1c:f6:a2:3b"


def _entries() -> dict[str, object]:
    """Записи A, B, B2, D (импорт `DeviceInfo` — здесь, чтобы красное было по поведению)."""
    from Services.camera_device.interface import DeviceInfo

    a = DeviceInfo(
        serial=SERIAL,
        model="MV-CS020-10GC",
        ip="192.168.1.20",
        mask="255.255.255.0",
        host_ip="169.254.49.100",
        mac="00:11:1c:f6:a2:3b",
    )
    b = DeviceInfo(
        serial=SERIAL,
        model="MV-CS020-10GC",
        ip="192.168.1.20",
        mask="255.255.255.0",
        host_ip="192.168.1.100",
        mac="00:11:1c:f6:a2:3b",
    )
    b2 = DeviceInfo(
        serial=SERIAL,
        model="MV-CS020-10GC",
        ip="192.168.1.20",
        mask="255.255.255.0",
        host_ip="192.168.1.101",
        mac="00:11:1c:f6:a2:3b",
    )
    d = DeviceInfo(
        serial=SERIAL,
        model="MV-CS020-10GC",
        ip="192.168.1.20",
        mask="255.255.255.0",
        host_ip="10.0.0.5",
        mac="00:11:1c:f6:a2:3b",
    )
    return {"A": a, "B": b, "B2": b2, "D": d}


# --------------------------------------------------------------------------------------------- #
# Стенд плагина
# --------------------------------------------------------------------------------------------- #


class _FakeProxy:
    """`state_proxy`: записывает `merge` (потокобезопасно)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.merges: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        with self.lock:
            self.merges.append((path, dict(data)))

    def set(self, path: str, value: object) -> None:
        pass

    def delete(self, path: str) -> None:
        pass

    def merged(self, key: str) -> list:
        with self.lock:
            return [data[key] for _, data in self.merges if key in data]


class _Rig:
    """Плагин над фейковым портом; `produce()` ведёт тест (как процесс-источник), окно тика — 0.05 с."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, **port_kwargs) -> None:
        monkeypatch.setattr(plugin_base, "_TICK_S", 0.05)
        self.port = make_port(frame_period_s=0.02, **port_kwargs)
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: self.port)
        config = {
            "auto_start": False,
            "camera_id": 3,
            "device_select": "serial",
            "device_serial": SERIAL,
        }
        self.services = MockProcessServices(name=PROCESS_NAME, config=config)
        self.wm = WorkerManager("test_cam_identity")
        self.services.worker_manager = self.wm  # настоящий менеджер: MockWorkerManager потоков не создаёт
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.proxy = _FakeProxy()
        self.ctx.state_proxy = self.proxy
        self.published: list[tuple[str, object]] = []
        publish = self.ctx.publish_metric
        self.ctx.publish_metric = lambda name, value: (self.published.append((name, value)), publish(name, value))[0]
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def take(self) -> dict:
        box: dict = {}
        thread = threading.Thread(target=lambda: box.update(r=self.plugin.cmd_take_device({})), daemon=True)
        thread.start()
        thread.join(DEADLINE_S)
        assert not thread.is_alive(), f"take_device не вернулся за {DEADLINE_S} с"
        return box["r"]

    def drive_until(self, predicate: Callable[[], bool], timeout: float = DEADLINE_S) -> bool:
        """Вести `produce()` с паузой 5 мс до выполнения условия или дедлайна."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.plugin.produce()
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def drive(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.plugin.produce()
            time.sleep(0.005)

    def log_msgs(self, level: str) -> list[str]:
        """Тексты журнала `MockProcessServices.logs` данного уровня с префиксом плагина."""
        return [e["msg"] for e in list(self.services.logs) if e["level"] == level and e["msg"].startswith(PREFIX)]

    def windows(self, start: int = 0) -> list[dict[str, object]]:
        """Опубликованные уровни, разрезанные на окна тика: новое окно — когда имя повторилось."""
        result: list[dict[str, object]] = []
        current: dict[str, object] = {}
        for name, value in list(self.published)[start:]:
            if name in current:
                result.append(current)
                current = {}
            current[name] = value
        if current:
            result.append(current)
        return result

    def first_window(self, predicate: Callable[[dict[str, object]], bool], start: int = 0) -> dict[str, object] | None:
        for window in self.windows(start):
            if predicate(window):
                return window
        return None

    def close(self) -> None:
        if getattr(self.plugin, "_session", None) is not None:
            self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(**port_kwargs) -> _Rig:
        rig = _Rig(monkeypatch, **port_kwargs)
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        rig.close()


# --------------------------------------------------------------------------------------------- #
# select_device (чистая функция)
# --------------------------------------------------------------------------------------------- #


def test_select_device_one_in_subnet_among_duplicates():
    from Services.camera_device.interface import DeviceIdentity, select_device

    import Services.camera_device as package

    e = _entries()
    index, info = select_device(DeviceIdentity("serial", SERIAL), (e["A"], e["B"]))
    assert index == 1
    assert info.host_ip == "192.168.1.100"
    assert info.enum_matches == 2
    assert tuple(info.enum_list) == (E_A, E_B)
    # имена экспортированы и из пакета (контракт брифа)
    assert package.select_device is select_device
    assert package.DeviceInfo is type(e["A"])


def test_select_device_lowest_host_ip_when_several_in_subnet():
    from Services.camera_device.interface import DeviceIdentity, select_device

    e = _entries()
    index, info = select_device(DeviceIdentity("serial", SERIAL), (e["B2"], e["B"]))
    assert index == 1
    assert info.host_ip == "192.168.1.100"
    assert info.enum_matches == 2
    assert tuple(info.enum_list) == (E_B2, E_B)


def test_select_device_refuses_when_none_in_subnet():
    from Services.camera_device.interface import AmbiguousDeviceError, DeviceIdentity, PortError, select_device

    e = _entries()
    with pytest.raises(AmbiguousDeviceError) as by_serial:
        select_device(DeviceIdentity("serial", SERIAL), (e["A"], e["D"]))
    assert by_serial.value.kind == "not_found"
    assert by_serial.value.where == "open"
    assert str(by_serial.value) == (
        "open: not_found: неоднозначное перечисление serial=DA1689923 записей=2, "
        "ни одна запись не в подсети камеры; записи: " + E_A + " | " + E_D
    )

    with pytest.raises(AmbiguousDeviceError) as by_ip:
        select_device(DeviceIdentity("ip", "192.168.1.20"), (e["A"], e["D"]))
    assert str(by_ip.value).startswith("open: not_found: неоднозначное перечисление ip=192.168.1.20 записей=2")

    with pytest.raises(PortError) as no_match:
        select_device(DeviceIdentity("serial", "X1"), (e["B"],))
    assert no_match.value.kind == "not_found"
    assert not isinstance(no_match.value, AmbiguousDeviceError)


# --------------------------------------------------------------------------------------------- #
# Плагин: строки лога и события личности
# --------------------------------------------------------------------------------------------- #


def test_single_entry_outside_subnet_used_with_warning(make):
    from Services.camera_device.interface import DeviceIdentity, select_device

    e = _entries()
    index, info = select_device(DeviceIdentity("serial", SERIAL), (e["A"],))
    assert index == 0
    assert info.enum_matches == 1

    rig = make(enum_entries=(e["A"],))
    assert rig.take()["status"] == "ok"
    expected = f"{PREFIX} serial={SERIAL} единственная запись вне подсети камеры: " + E_A
    assert rig.drive_until(lambda: bool(rig.log_msgs("WARNING"))), "WARNING не появился"
    rig.drive(0.2)
    assert rig.log_msgs("WARNING") == [expected]
    # захват идёт
    assert rig.drive_until(lambda: rig.proxy.merged("state")[-1:] == ["grabbing"]), rig.proxy.merged("state")
    assert rig.drive_until(lambda: any(v > 0 for n, v in rig.published if n == "frames")), "кадры не идут"


def test_duplicate_enumeration_warning_and_identity_block(make):
    e = _entries()
    rig = make(enum_entries=(e["A"], e["B"]))
    assert rig.take()["status"] == "ok"
    expected = (
        f"{PREFIX} serial={SERIAL} перечислен 2 раз; выбрана запись host_ip=192.168.1.100; записи: " + E_A + " | " + E_B
    )
    assert rig.drive_until(lambda: bool(rig.log_msgs("WARNING")) and bool(rig.proxy.merged("identity")))
    rig.drive(0.2)
    assert rig.log_msgs("WARNING") == [expected]
    identity = rig.proxy.merged("identity")[-1]
    assert identity["host_ip"] == "192.168.1.100"
    assert identity["mac"] == "00:11:1c:f6:a2:3b"
    assert identity["enum_matches"] == 2
    assert list(identity["enum_list"]) == [E_A, E_B]


def test_ambiguous_enumeration_gives_not_found_with_list(make):
    e = _entries()
    rig = make(enum_entries=(e["A"], e["D"]))
    rig.take()
    assert rig.drive_until(lambda: "not_found" in rig.proxy.merged("state")), rig.proxy.merged("state")
    assert rig.proxy.merged("state")[-1] == "not_found"
    assert rig.drive_until(lambda: bool(rig.proxy.merged("last_error"))), "last_error не опубликован"
    last_error = rig.proxy.merged("last_error")[-1]
    assert "host_ip=169.254.49.100" in last_error
    assert "host_ip=10.0.0.5" in last_error


# --------------------------------------------------------------------------------------------- #
# Здоровье потока: счётчики потерь
# --------------------------------------------------------------------------------------------- #


def test_lost_frames_incomplete_lost_packets(make):
    rig = make(frame_meta=((1, 0, None), (2, 3, None), (5, 0, None)))
    assert rig.take()["status"] == "ok"
    names = {"lost_frames", "incomplete", "lost_packets"}
    assert rig.drive_until(lambda: rig.first_window(lambda w: w.get("lost_packets") == 3) is not None), rig.windows()
    window = rig.first_window(lambda w: w.get("lost_packets") == 3)
    assert names <= set(window)
    assert window["lost_frames"] == 2
    assert window["incomplete"] == 1
    assert window["lost_packets"] == 3

    # reset_stats: следующее окно — все три нуля
    box: dict = {}
    thread = threading.Thread(target=lambda: box.update(r=rig.plugin.cmd_reset_stats({})), daemon=True)
    thread.start()
    thread.join(DEADLINE_S)
    assert not thread.is_alive(), "reset_stats не вернулся"
    assert box["r"] == {"success": True}
    mark = len(rig.published)
    assert rig.drive_until(lambda: any(names <= set(w) for w in rig.windows(mark))), rig.windows(mark)
    after = next(w for w in rig.windows(mark) if names <= set(w))
    assert after["lost_frames"] == 0
    assert after["incomplete"] == 0
    assert after["lost_packets"] == 0


def test_trigger_lost_counts_index_gaps(make):
    rig = make(frame_meta=((1, 0, 10), (2, 0, 11), (3, 0, 14)))
    assert rig.take()["status"] == "ok"
    assert rig.drive_until(lambda: rig.first_window(lambda w: w.get("trigger_lost") == 2) is not None), rig.windows()
    window = rig.first_window(lambda w: w.get("trigger_lost") == 2)
    assert window["trigger_lost"] == 2
    assert window["lost_frames"] == 0


# --------------------------------------------------------------------------------------------- #
# Блок stream и информационная строка открытия
# --------------------------------------------------------------------------------------------- #


def test_stream_block_and_open_info_line(make):
    e = _entries()
    rig = make(enum_entries=(e["B"],))
    assert rig.take()["status"] == "ok"
    fmt, width, height = fake_port.FRAME_PIXEL_FORMAT, fake_port.FRAME_WIDTH, fake_port.FRAME_HEIGHT
    expected = (
        f"{PREFIX} device opened serial={SERIAL} model=MV-CS020-10GC ip=192.168.1.20 mask=255.255.255.0 "
        f"host_ip=192.168.1.100 mac=00:11:1c:f6:a2:3b pixel_format={fmt} width={width} height={height} enum_matches=1"
    )
    assert rig.drive_until(lambda: bool(rig.proxy.merged("stream")) and expected in rig.log_msgs("INFO"))
    rig.drive(0.2)
    assert rig.proxy.merged("stream")[-1] == {"pixel_format": fmt, "width": width, "height": height}
    opened = [m for m in rig.log_msgs("INFO") if m.startswith(f"{PREFIX} device opened")]
    assert opened == [expected]
    assert rig.log_msgs("WARNING") == []


# --------------------------------------------------------------------------------------------- #
# Фейковый порт: device_info
# --------------------------------------------------------------------------------------------- #


def test_fake_device_info_lifecycle():
    from Services.camera_device.interface import DeviceIdentity, DevicePort

    port = make_port()
    assert port.device_info is None
    assert isinstance(port, DevicePort)
    box: dict = {}

    def run() -> None:
        port.open(DeviceIdentity("serial", "00DB2156580"))
        box["serial"] = port.device_info.serial if port.device_info is not None else None
        port.close()
        box["after_close"] = port.device_info
        box["done"] = True

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(DEADLINE_S)
    assert not thread.is_alive(), "open/close фейка не вернулись"
    assert box.get("serial") == "00DB2156580"
    assert box["after_close"] is None
