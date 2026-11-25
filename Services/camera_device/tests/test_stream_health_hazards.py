# -*- coding: utf-8 -*-
"""Опасности W1-a (автор кода): гонки счётчиков потока, строка открытия раз за цикл, жизнь `identity`/`stream`.

Свойства, которые охраняются (каждый тест называет своё):
- два потока на событие `grabbing` дают ровно одну строку открытия и не больше одного предупреждения;
- `reset_stats` посреди потока кадров не рвёт парные счётчики (`incomplete` и `lost_packets` растут и сбрасываются
  вместе под одним замком, `_tick` читает их одним снимком);
- номера кадров и триггера прошлого цикла — не опора нового: разрыв через `opening` не считается потерей, а
  накопленные счётчики на `opening` не обнуляются;
- порт без `device_info` (заглушка) даёт строку с прочерками и `identity: None`;
- `identity` переживает перезахват внутри `grabbing` и становится `None` после `release` и при отказе открытия;
  следующий цикл, чей порт личности не даёт, не наследует личность прошлого.

Стенд как у `test_identity_stream_contract.py`, но свой: настоящие `CameraDevicePlugin`, `PluginContext` над
`MockProcessServices`, настоящий `WorkerManager`; подменены `plugin_base.create_port`, `state_proxy` и
`publish_metric` (запись). Ожидаемые значения — литералы. Вызов, который может зависнуть, идёт в daemon-потоке с
`join(timeout)`.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import (
    AmbiguousDeviceError,
    DeviceIdentity,
    DeviceInfo,
    RawFrame,
    select_device,
)
from Services.camera_device.params import Step
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import FAKE_BINDINGS, make_port

PREFIX = "CameraDevicePlugin:"
SERIAL = "DA1689923"
DEADLINE_S = 10.0
OPENED = f"{PREFIX} device opened"

IN_NET = DeviceInfo(
    serial=SERIAL,
    model="MV-CS020-10GC",
    ip="192.168.1.20",
    mask="255.255.255.0",
    host_ip="192.168.1.100",
    mac="00:11:1c:f6:a2:3b",
)
OFF_NET = DeviceInfo(
    serial=SERIAL,
    model="MV-CS020-10GC",
    ip="192.168.1.20",
    mask="255.255.255.0",
    host_ip="169.254.49.100",
    mac="00:11:1c:f6:a2:3b",
)
OTHER_NET = DeviceInfo(
    serial=SERIAL,
    model="MV-CS020-10GC",
    ip="192.168.1.20",
    mask="255.255.255.0",
    host_ip="10.0.0.5",
    mac="00:11:1c:f6:a2:3b",
)


def _frame(num: int, *, lost: int = 0, trigger: int | None = None) -> RawFrame:
    return RawFrame(
        data=bytearray(range(8)),
        width=4,
        height=2,
        pixel_format="mono8",
        frame_num=num,
        lost_packets=lost,
        trigger_index=trigger,
    )


class _Proxy:
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


class _NoInfoPort:
    """Порт-заглушка вендора без `device_info`: всё делегируется фейку, кроме самого атрибута."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        if name == "device_info":
            raise AttributeError(name)
        return getattr(self._inner, name)


class _ForgetfulPort:
    """Порт, чей `device_info` после `forget = True` отвечает `None`: личность в одном цикле есть, в следующем нет."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.forget = False

    def __getattr__(self, name: str):
        if name == "device_info" and self.forget:
            return None
        return getattr(self._inner, name)


class _Rig:
    """Плагин над портом; `produce()` ведёт тест (как процесс-источник), окно тика 0.05 с."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, wrap=None, **port_kwargs) -> None:
        monkeypatch.setattr(plugin_base, "_TICK_S", 0.05)
        self.fake = make_port(frame_period_s=0.02, **port_kwargs)
        self.port = self.fake if wrap is None else wrap(self.fake)
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: self.port)
        config = {"auto_start": False, "camera_id": 4, "device_select": "serial", "device_serial": SERIAL}
        self.services = MockProcessServices(name="cam_health", config=config)
        self.wm = WorkerManager("test_cam_health")
        self.services.worker_manager = self.wm  # настоящий менеджер: MockWorkerManager потоков не создаёт
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.proxy = _Proxy()
        self.ctx.state_proxy = self.proxy
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def _call(self, fn: Callable[[], dict]) -> dict:
        box: dict = {}
        thread = threading.Thread(target=lambda: box.update(r=fn()), daemon=True)
        thread.start()
        thread.join(DEADLINE_S)
        assert not thread.is_alive(), f"команда не вернулась за {DEADLINE_S} с"
        return box["r"]

    def take(self) -> dict:
        return self._call(lambda: self.plugin.cmd_take_device({}))

    def release(self) -> dict:
        return self._call(lambda: self.plugin.cmd_release_device({}))

    def drive_until(self, predicate: Callable[[], bool], timeout: float = DEADLINE_S) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.plugin.produce()
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def drive(self, seconds: float) -> None:
        self.drive_until(lambda: False, seconds)

    def state(self) -> str | None:
        merged = self.proxy.merged("state")
        return merged[-1] if merged else None

    def log_msgs(self, level: str, prefix: str = PREFIX) -> list[str]:
        return [e["msg"] for e in list(self.services.logs) if e["level"] == level and e["msg"].startswith(prefix)]

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


class _Unit:
    """Плагин без сеанса и воркеров: `_on_frame`/`_on_state`/`_tick` зовёт тест; уровни пишутся в `published`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, port=None) -> None:
        monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)  # каждый `_tick()` публикует
        self.port = port
        if port is not None:
            monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        config = {"auto_start": False, "camera_id": 5, "device_select": "serial", "device_serial": SERIAL}
        self.services = MockProcessServices(name="cam_unit", config=config)
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.published: list[tuple[str, object]] = []
        self.published_lock = threading.Lock()
        publish = self.ctx.publish_metric

        def record(name: str, value: object) -> None:
            with self.published_lock:
                self.published.append((name, value))
            publish(name, value)

        self.ctx.publish_metric = record
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def levels(self) -> dict[str, object]:
        """Один `_tick()` и значения этого окна (последние по имени)."""
        with self.published_lock:
            mark = len(self.published)
        self.plugin._tick()
        with self.published_lock:
            return dict(self.published[mark:])

    def losses(self) -> tuple[object, object, object, object]:
        window = self.levels()
        return window["incomplete"], window["lost_packets"], window["lost_frames"], window["trigger_lost"]

    def log_msgs(self, level: str) -> list[str]:
        return [e["msg"] for e in list(self.services.logs) if e["level"] == level and e["msg"].startswith(PREFIX)]


@pytest.fixture
def fast_switch():
    """Частая смена потоков: окно гонки между проверкой и записью становится заметным."""
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(old)


# --------------------------------------------------------------------------------------------- #
# Гонки
# --------------------------------------------------------------------------------------------- #


def test_concurrent_grabbing_events_log_once(monkeypatch, fast_switch):
    """Охраняет: test-and-set `_open_logged` атомарен — два потока на `grabbing` дают одну INFO и одну WARNING."""
    port = make_port(enum_entries=(OFF_NET, IN_NET))
    unit = _Unit(monkeypatch, port=port)
    unit.plugin._ensure_port()
    port.sdk.acquire()
    port.open(DeviceIdentity("serial", SERIAL))  # `device_info`: две записи, выбрана host_ip=192.168.1.100
    assert port.device_info.enum_matches == 2

    for round_no in range(300):
        unit.plugin._on_state("closed", "opening")  # новый цикл: флаг сброшен
        before = len(unit.services.logs)
        barrier = threading.Barrier(2)

        def fire() -> None:
            barrier.wait(DEADLINE_S)
            unit.plugin._on_state("opening", "grabbing")

        threads = [threading.Thread(target=fire, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(DEADLINE_S)
            assert not thread.is_alive(), f"_on_state не вернулся (раунд {round_no})"
        new = [e for e in list(unit.services.logs)[before:] if e["msg"].startswith(PREFIX)]
        opened = [e for e in new if e["level"] == "INFO" and e["msg"].startswith(OPENED)]
        warned = [e for e in new if e["level"] == "WARNING"]
        assert len(opened) == 1, f"раунд {round_no}: строк открытия {len(opened)}"
        assert len(warned) == 1, f"раунд {round_no}: предупреждений {len(warned)}"


def test_reset_stats_races_on_frame(monkeypatch, fast_switch):
    """Охраняет: `reset_stats` не рвёт пару `incomplete`/`lost_packets` и не роняет `_on_frame` и `_tick`."""
    unit = _Unit(monkeypatch)
    errors: list[BaseException] = []
    stop = threading.Event()

    def guarded(fn: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 — поток теста: причина уйдёт в assert ниже
                errors.append(exc)

        return run

    def produce_frames() -> None:
        number = 0
        unit.plugin._on_frame(_frame(number, lost=1))  # опорный кадр: разрыва нет
        for _ in range(3000):
            number += 2  # каждый следующий кадр: пропущен один номер и потерян один пакет
            unit.plugin._on_frame(_frame(number, lost=1))
        stop.set()

    def reset_often() -> None:
        while not stop.is_set():
            assert unit.plugin.cmd_reset_stats({}) == {"success": True}

    snapshots: list[tuple[object, object, object]] = []

    def read_often() -> None:
        while not stop.is_set():
            window = unit.levels()
            if "incomplete" not in window:  # `_tick` ушёл рано: `reset_stats` сдвинул окно между `now` и замком
                continue
            snapshots.append((window["incomplete"], window["lost_packets"], window["lost_frames"]))

    threads = [threading.Thread(target=guarded(fn), daemon=True) for fn in (produce_frames, reset_often, read_often)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(DEADLINE_S)
        assert not thread.is_alive(), "поток теста не завершился"
    assert errors == []
    assert snapshots, "читатель не снял ни одного окна"
    for incomplete, lost_packets, lost_frames in snapshots:
        assert incomplete == lost_packets, (incomplete, lost_packets, lost_frames)  # пара не разорвана
        assert 0 <= incomplete - lost_frames <= 1, (incomplete, lost_packets, lost_frames)

    assert unit.plugin.cmd_reset_stats({}) == {"success": True}
    assert unit.losses() == (0, 0, 0, 0)  # после сброса и без кадров — нули


# --------------------------------------------------------------------------------------------- #
# Опорные номера и накопление
# --------------------------------------------------------------------------------------------- #


def test_baseline_reset_on_opening_not_counted(monkeypatch):
    """Охраняет: разрыв номера через `opening` — не потеря; счётчики на `opening` не обнуляются; `<=` не считается."""
    unit = _Unit(monkeypatch)
    unit.plugin._on_frame(_frame(10, trigger=100))
    unit.plugin._on_frame(_frame(11, trigger=101))
    assert unit.losses() == (0, 0, 0, 0)

    unit.plugin._on_state("closed", "opening")  # новый цикл: опора сброшена
    unit.plugin._on_frame(_frame(1000, trigger=5000))
    assert unit.losses() == (0, 0, 0, 0)

    unit.plugin._on_frame(_frame(1010, trigger=5010))  # тот же цикл: разрыв настоящий (9 и 9)
    assert unit.losses() == (0, 0, 9, 9)

    unit.plugin._on_frame(_frame(3, trigger=2))  # номер не больше прежнего (перезахват, сброс счётчика прибора)
    unit.plugin._on_frame(_frame(4, trigger=3))
    assert unit.losses() == (0, 0, 9, 9)

    unit.plugin._on_state("closed", "opening")  # накопленное остаётся
    assert unit.losses() == (0, 0, 9, 9)


def test_trigger_index_none_keeps_trigger_baseline(monkeypatch):
    """Охраняет: кадр без `trigger_index` (драйвер его не даёт) не трогает опору триггера."""
    unit = _Unit(monkeypatch)
    unit.plugin._on_frame(_frame(1, trigger=7))
    unit.plugin._on_frame(_frame(2))  # без индекса: опора триггера остаётся 7
    unit.plugin._on_frame(_frame(3, trigger=9))  # разрыв 7 -> 9: потерян один
    assert unit.losses() == (0, 0, 0, 1)


# --------------------------------------------------------------------------------------------- #
# Заглушка порта и жизнь identity
# --------------------------------------------------------------------------------------------- #


def test_stub_port_without_device_info_logs_dashes(make):
    """Охраняет: порт без `device_info` не роняет плагин; строка входа в захват — с прочерками, раз за цикл."""
    rig = make(wrap=_NoInfoPort, enum_entries=(IN_NET,))  # перечисление знает SERIAL; `device_info` заглушка прячет
    assert not hasattr(rig.port, "device_info")
    assert rig.take()["status"] == "ok"
    expected = (
        f"{PREFIX} device opened serial=- model=- ip=- mask=- host_ip=- mac=- pixel_format=- width=- height=- "
        "enum_matches=-"
    )
    assert rig.drive_until(lambda: rig.state() == "grabbing" and bool(rig.proxy.merged("identity")))
    rig.drive(0.2)
    assert rig.log_msgs("INFO", OPENED) == [expected]
    assert [m for m in rig.log_msgs("WARNING") if "serial=" in m] == []
    assert rig.proxy.merged("identity")[-1] is None


def test_identity_survives_regrab(make):
    """Охраняет: перезахват без `restart_regrab` закрывает порт внутри `grabbing`, `identity` не мигает `None`."""
    rig = make(open_delay_s=0.3, capabilities=fake_port.ALL_CAPABILITIES - {"restart_regrab"}, enum_entries=(IN_NET,))
    assert rig.take()["status"] == "ok"
    assert rig.drive_until(lambda: any(v is not None for v in rig.proxy.merged("identity")))
    session = rig.plugin._session
    step = Step("exposure_time", FAKE_BINDINGS["exposure_time"], 20000.0)
    session.apply([step], "restart")

    saw_closed_port = False

    def regrab_done() -> bool:
        nonlocal saw_closed_port
        if rig.fake.device_info is None and session.state == "grabbing":
            saw_closed_port = True  # окно перезахвата: порт закрыт, цикл `grabbing`
        opens = sum(1 for call in list(rig.fake.calls) if call[0] == "open")
        return opens == 2 and rig.fake.device_info is not None

    assert rig.drive_until(regrab_done), [call[0] for call in rig.fake.calls]
    rig.drive(0.2)
    assert saw_closed_port, "окно перезахвата не наблюдалось: тест ничего не доказывает"
    assert session.state == "grabbing"
    values = rig.proxy.merged("identity")
    first = next(i for i, value in enumerate(values) if value is not None)
    assert all(value is not None for value in values[first:]), values
    assert values[-1]["serial"] == SERIAL


def test_identity_none_after_release_and_reopen_refused(make):
    """Охраняет: после `release` и при отказе нового открытия `identity`/`stream` — `None`, не прежний прибор."""
    rig = make(enum_entries=(IN_NET,))
    assert rig.take()["status"] == "ok"
    assert rig.drive_until(
        lambda: rig.proxy.merged("identity")[-1:] != [None] and rig.proxy.merged("stream")[-1:] != [None]
    )
    assert rig.proxy.merged("identity")[-1]["serial"] == SERIAL

    assert rig.release()["status"] == "ok"
    assert rig.drive_until(lambda: rig.state() == "closed"), rig.proxy.merged("state")
    assert rig.drive_until(lambda: rig.proxy.merged("identity")[-1] is None), rig.proxy.merged("identity")

    rig.plugin._reg.device_serial = "NO-SUCH-0000"  # следующий цикл: такого прибора в перечислении нет
    assert rig.take()["status"] == "error"
    assert rig.drive_until(lambda: rig.state() == "not_found"), rig.proxy.merged("state")
    rig.drive(0.2)
    assert rig.proxy.merged("identity")[-1] is None
    assert rig.proxy.merged("stream")[-1] is None  # формат прошлого цикла не наследуется


def test_identity_none_after_refusal(make):
    """Охраняет: первый же цикл с отказом открытия (`not_found`) даёт `identity` `None` и ни одной строки открытия."""
    rig = make(enum_entries=(OFF_NET, OTHER_NET))  # две записи, ни одна не в подсети: `AmbiguousDeviceError`
    assert rig.take()["status"] == "error"
    assert rig.drive_until(lambda: rig.state() == "not_found"), rig.proxy.merged("state")
    rig.drive(0.2)
    assert rig.fake.device_info is None
    assert all(value is None for value in rig.proxy.merged("identity"))
    assert rig.log_msgs("INFO", OPENED) == []


def test_identity_not_inherited_by_next_grabbing_without_device_info(make):
    """Охраняет: сброс на `opening` — личность цикла 1 не выдаётся за личность цикла 2, где порт её не даёт."""
    rig = make(wrap=_ForgetfulPort, enum_entries=(IN_NET,))
    assert rig.take()["status"] == "ok"
    assert rig.drive_until(lambda: any(value is not None for value in rig.proxy.merged("identity")))
    assert rig.proxy.merged("identity")[-1]["serial"] == "DA1689923"
    assert rig.release()["status"] == "ok"
    assert rig.drive_until(lambda: rig.state() == "closed" and rig.proxy.merged("identity")[-1] is None)

    rig.port.forget = True  # цикл 2: порт открывается, но личности не даёт
    assert rig.take()["status"] == "ok"
    assert rig.drive_until(lambda: rig.state() == "grabbing"), rig.proxy.merged("state")
    rig.drive(0.3)  # несколько окон тика в `grabbing`: подстановке прошлой личности есть где сработать
    assert rig.state() == "grabbing"
    assert rig.proxy.merged("identity")[-1] is None


# --------------------------------------------------------------------------------------------- #
# Маска 0.0.0.0: подсеть неизвестна
# --------------------------------------------------------------------------------------------- #

ZERO_MASK_LINKLOCAL = DeviceInfo(
    serial=SERIAL,
    model="MV-CS020-10GC",
    ip="192.168.1.20",
    mask="0.0.0.0",
    host_ip="169.254.49.100",
    mac="00:11:1c:f6:a2:3b",
)
ZERO_MASK_IN_NET = DeviceInfo(
    serial=SERIAL,
    model="MV-CS020-10GC",
    ip="192.168.1.20",
    mask="0.0.0.0",
    host_ip="192.168.1.100",
    mac="00:11:1c:f6:a2:3b",
)
ZERO_E_LINKLOCAL = "ip=192.168.1.20 mask=0.0.0.0 host_ip=169.254.49.100 mac=00:11:1c:f6:a2:3b"
ZERO_E_IN_NET = "ip=192.168.1.20 mask=0.0.0.0 host_ip=192.168.1.100 mac=00:11:1c:f6:a2:3b"


def test_zero_mask_duplicates_are_refused_with_list():
    """Охраняет: маска 0.0.0.0 не делает всякий хост "в подсети" — дубли отклоняются с перечнем записей."""
    with pytest.raises(AmbiguousDeviceError) as exc_info:
        select_device(DeviceIdentity("serial", SERIAL), (ZERO_MASK_LINKLOCAL, ZERO_MASK_IN_NET))
    assert str(exc_info.value).endswith("записи: " + ZERO_E_LINKLOCAL + " | " + ZERO_E_IN_NET)


def test_zero_mask_single_entry_opens_with_warning(make):
    """Охраняет: единственная запись с маской 0.0.0.0 открывается, а оператор видит предупреждение."""
    rig = make(enum_entries=(ZERO_MASK_LINKLOCAL,))
    assert rig.take()["status"] == "ok"

    def warned() -> list[str]:
        return [m for m in rig.log_msgs("WARNING") if "serial=" in m]

    assert rig.drive_until(lambda: rig.state() == "grabbing" and bool(warned())), rig.log_msgs("WARNING")
    rig.drive(0.2)
    assert warned() == [f"{PREFIX} serial=DA1689923 единственная запись вне подсети камеры: " + ZERO_E_LINKLOCAL]
