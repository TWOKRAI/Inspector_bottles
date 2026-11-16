# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 2.3d: команды прибора плагина (`list_devices`, `describe_params`, `trigger_software`).

Гонки и порядок: выбор пути `list_devices` по `device_held` (медленный `close` + `stop`), `call` против `stop`,
освобождение `acquire` при отказе, срок и отмена команды при занятом владельце, один порт при параллельных
командах, отказ `create_port`, замок `refs` фейка. Настоящий `CameraDevicePlugin` + фейк порта + `WorkerManager`.
Ожидаемые значения — литералы. Любой вызов, который может зависнуть, идёт в daemon-потоке с дедлайном `join`.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import PortError
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing.fake_port import make_port

pytestmark = pytest.mark.timeout(60)

CFG = {"auto_start": False, "camera_id": 4, "device_select": "serial", "device_serial": "FAKE-0001"}
LISTED = {"success": True, "devices": [{"kind": "serial", "value": "FAKE-0001", "name": ""}]}
NOT_GRABBING = {"success": False, "error": "сеанс не в захвате"}
CALL_REFUSALS = ("срок", "сеанс остановлен", "сеанс не в захвате")


class _Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, port) -> None:
        self.port = port
        self.create_port_calls = 0
        monkeypatch.setattr(plugin_base, "create_port", self._create_port)
        services = MockProcessServices(name="cam_cmds_hz", config=dict(CFG))
        self.wm = WorkerManager("test_cam_cmds_hz")
        services.worker_manager = self.wm
        self.ctx = PluginContext(services=services, config=dict(CFG))
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def _create_port(self, driver: str):
        self.create_port_calls += 1
        return self.port

    def count(self, name: str) -> int:
        return sum(1 for call in list(self.port.calls) if call[0] == name)

    def names(self, start: int = 0) -> list[str]:
        return [name for name, _args, _tid in list(self.port.calls)[start:] if name != "get_frame"]

    def close(self) -> None:
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(port=None) -> _Rig:
        rig = _Rig(monkeypatch, port if port is not None else make_port(frame_period_s=0.02))
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        try:
            rig.close()
        except Exception:  # noqa: BLE001 — teardown не маскирует падение теста
            pass


def _bg(fn):
    """`fn` в daemon-потоке без ожидания: `(поток, {"result": ...})`."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается тесту
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    return worker, box


def _join(worker, box, deadline: float = 8.0):
    worker.join(deadline)
    assert not worker.is_alive(), f"поток не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _call(fn, deadline: float = 8.0):
    return _join(*_bg(fn), deadline)


def _await(predicate, what: str, deadline: float = 4.0) -> None:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail(f"за {deadline} с не случилось: {what}")


def _take(rig: _Rig) -> None:
    assert _call(lambda: rig.plugin.cmd_take_device({}))["status"] == "ok"


def _hang_owner(rig: _Rig, seconds: float) -> None:
    """Владелец застревает в `get_frame` на `seconds`; возврат, когда зависание уже началось."""
    rig.port.arm_hang(seconds)
    _await(lambda: rig.port._hang_s == 0.0, "get_frame начал зависание")


# -- выбор пути list_devices: device_held, а не state --------------------------------------------------------------


def test_list_devices_при_медленном_close_после_stop_отказывает_и_порт_не_зовётся(make):
    port = make_port(frame_period_s=0.01, get_frame_errors=3)
    original_close = port.close

    def slow_close() -> None:
        time.sleep(2.0)  # владелец задерживается в cleanup, `state` уже `closed`, `device_held` ещё истинно
        original_close()

    port.close = slow_close
    rig = make(port)
    worker, box = _bg(lambda: rig.plugin.cmd_take_device({}))
    _await(lambda: rig.plugin.cmd_get_status({})["state"] == "error", "три ошибки get_frame -> error")
    released = _call(lambda: rig.plugin.cmd_release_device({"timeout_s": 0.05}))
    assert released["device_state"] == "closed"
    assert released["status"] == "error"  # владелец ещё закрывает прибор: `device_held` истинно
    acquires, enums, releases = rig.count("acquire"), rig.count("enum_devices"), rig.count("release")
    assert enums == 1  # единственное перечисление — самого владельца при открытии

    assert _call(lambda: rig.plugin.cmd_list_devices({})) == NOT_GRABBING

    assert (rig.count("acquire"), rig.count("enum_devices"), rig.count("release")) == (acquires, enums, releases)
    _join(worker, box)
    # `refs == 0` не признак выхода владельца: `release` идёт раньше снятия `device_held` (после него стоп сторожа).
    # Выход виден по `release_device`: он отвечает `ok` только когда `device_held` снят.
    _await(lambda: rig.plugin.cmd_release_device({})["status"] == "ok", "владелец вышел", deadline=6.0)
    assert rig.port.sdk.refs == 0
    # владельца больше нет: теперь перечисление идёт потоком команды (контроль: путь выбирался по `device_held`)
    base = len(rig.port.calls)
    assert _call(lambda: rig.plugin.cmd_list_devices({})) == LISTED
    assert rig.names(base) == ["acquire", "enum_devices", "release"]


def test_list_devices_после_отказа_открытия_и_release_идёт_потоком_команды(make):
    rig = make(make_port(frame_period_s=0.01, busy_for_s=30.0))
    result = _call(lambda: rig.plugin.cmd_take_device({}))
    assert result["status"] == "error"
    assert _call(lambda: rig.plugin.cmd_release_device({}))["status"] == "ok"  # владелец вышел
    base = len(rig.port.calls)
    assert _call(lambda: rig.plugin.cmd_list_devices({})) == LISTED
    assert rig.names(base) == ["acquire", "enum_devices", "release"]
    assert rig.port.sdk.refs == 0


# -- call против stop ------------------------------------------------------------------------------------------------


def test_list_devices_при_захвате_против_stop_отвечает_и_не_виснет(make):
    rig = make()
    for _ in range(12):
        _take(rig)
        gate = threading.Event()

        def lister() -> dict:
            gate.wait(2.0)
            return rig.plugin.cmd_list_devices({})

        def stopper() -> dict:
            gate.wait(2.0)
            return rig.plugin.cmd_release_device({})

        list_thread, list_box = _bg(lister)
        stop_thread, stop_box = _bg(stopper)
        gate.set()
        answer = _join(list_thread, list_box)
        _join(stop_thread, stop_box)
        assert answer == LISTED or (answer["success"] is False and answer["error"] in CALL_REFUSALS), answer
    assert rig.port.sdk.refs == 0


# -- отказы порта и освобождение acquire --------------------------------------------------------------------------


def test_отказ_enum_devices_без_захвата_отпускает_acquire(make):
    rig = make()
    sdk = rig.port.sdk
    original = sdk.enum_devices

    def failing():
        original()  # запись в журнал порта
        raise PortError("network", "enum_devices")

    sdk.enum_devices = failing
    answer = _call(lambda: rig.plugin.cmd_list_devices({}))
    assert answer == {"success": False, "error": "PortError kind=network: enum_devices: network"}
    assert rig.names() == ["acquire", "enum_devices", "release"]
    assert sdk.refs == 0


def test_отказ_acquire_release_не_зовётся(make):
    rig = make()
    sdk = rig.port.sdk

    def failing() -> None:
        sdk._journal("acquire", ())
        raise PortError("other", "acquire")

    sdk.acquire = failing
    answer = _call(lambda: rig.plugin.cmd_list_devices({}))
    assert answer == {"success": False, "error": "PortError kind=other: acquire: other"}
    assert rig.names() == ["acquire"]  # `release` без `acquire` бросил бы RuntimeError и сломал счёт
    assert sdk.refs == 0


def test_отказ_release_после_перечисления_отвечает_отказом_а_не_исключением(make):
    rig = make()
    sdk = rig.port.sdk

    def failing() -> None:
        sdk._journal("release", ())
        raise PortError("other", "release")

    sdk.release = failing
    answer = _call(lambda: rig.plugin.cmd_list_devices({}))
    assert answer["success"] is False
    assert answer["error"] == "PortError kind=other: release: other"


# -- порт создаётся отдельно от сеанса ----------------------------------------------------------------------------


def test_отказ_create_port_отвечает_отказом_и_следующая_команда_создаёт_порт(make, monkeypatch):
    attempts: list[int] = []
    good = make_port(frame_period_s=0.02)

    def flaky(driver: str):
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("нет такого драйвера")
        if len(attempts) == 2:
            raise OSError("DLL")
        return good

    rig = make()
    monkeypatch.setattr(plugin_base, "create_port", flaky)
    assert _call(lambda: rig.plugin.cmd_list_devices({})) == {"success": False, "error": "нет такого драйвера"}
    assert _call(lambda: rig.plugin.cmd_describe_params({})) == {"success": False, "error": "OSError"}
    assert rig.plugin._port is None  # порт не залип на неудачной попытке
    assert _call(lambda: rig.plugin.cmd_list_devices({})) == LISTED
    assert len(attempts) == 3
    assert rig.plugin._session is None


def test_параллельные_list_devices_создают_один_порт_и_сводят_ссылки_в_ноль(make, monkeypatch):
    rig = make()
    original = rig._create_port

    def slow_create(driver: str):
        time.sleep(0.1)  # окно: без замка второй поток тоже увидел бы `_port is None`
        return original(driver)

    monkeypatch.setattr(plugin_base, "create_port", slow_create)
    gate = threading.Event()

    def lister() -> dict:
        gate.wait(2.0)
        return rig.plugin.cmd_list_devices({})

    started = [_bg(lister) for _ in range(4)]
    gate.set()
    answers = [_join(worker, box) for worker, box in started]
    assert answers == [LISTED] * 4
    assert rig.create_port_calls == 1
    assert rig.port.sdk.refs == 0
    assert rig.count("acquire") == 4 and rig.count("release") == 4


def test_take_device_после_list_devices_не_виснет_на_замке_сеанса(make):
    rig = make()
    assert _call(lambda: rig.plugin.cmd_list_devices({})) == LISTED
    _take(rig)  # `_ensure_session` берёт `_session_lock` и строит сеанс из порта, созданного командой
    assert rig.create_port_calls == 1
    assert rig.plugin._session is not None


# -- срок и отмена команды при занятом владельце ---------------------------------------------------------------


@pytest.mark.parametrize(
    "command, journal_name", [("trigger_software", "execute"), ("describe_params", "describe_param")]
)
def test_команда_по_сроку_отвечает_срок_и_позже_не_исполняется(make, monkeypatch, command, journal_name):
    monkeypatch.setattr(plugin_base, "_CALL_TIMEOUT_S", 0.1)
    rig = make()
    _take(rig)
    before = rig.count(journal_name)
    _hang_owner(rig, 0.8)  # владелец занят `get_frame` и до команды не дойдёт

    t0 = time.monotonic()
    answer = _call(lambda: getattr(rig.plugin, f"cmd_{command}")({}))
    elapsed = time.monotonic() - t0

    assert answer == {"success": False, "error": "срок"}
    assert elapsed < 0.7  # ответ по сроку, а не после зависания
    time.sleep(1.0)  # владелец вернулся в цикл: отменённая команда обязана быть пропущена
    assert rig.count(journal_name) == before


# -- describe_params: все привязки одним call, отказ узла, отказ хука ---------------------------------------------


def test_describe_params_все_describe_param_идут_подряд_одним_call(make):
    rig = make()
    _take(rig)
    base = len(rig.port.calls)
    answer = _call(lambda: rig.plugin.cmd_describe_params({}))
    assert answer["success"] is True
    # при одном `call` владелец исполняет весь пакет, не возвращаясь в цикл; при `call` на привязку между
    # записями был бы `get_frame` (следующий `call` ставится только после ответа предыдущего)
    names = [name for name, _args, _tid in rig.port.calls[base:]]
    first = names.index("describe_param")
    last = len(names) - 1 - names[::-1].index("describe_param")
    assert names[first : last + 1] == ["describe_param"] * (last - first + 1)
    assert last - first + 1 == len(answer["params_meta"])  # по записи на привязку


def test_describe_params_describe_param_вернул_none_даёт_null_только_для_этого_поля(make):
    rig = make()
    _take(rig)
    original = rig.port.describe_param

    def patched(binding):
        info = original(binding)  # запись в журнал порта и реальный ответ фейка
        return None if binding.key == "ExposureTime" else info

    rig.port.describe_param = patched
    answer = _call(lambda: rig.plugin.cmd_describe_params({}))
    assert answer["success"] is True
    meta = answer["params_meta"]
    assert meta["exposure_time"] is None
    assert meta["trigger_mode"] == {"min": None, "max": None, "inc": None, "entries": ["Off", "On"], "access": "RO"}
    assert all(value is not None for field, value in meta.items() if field != "exposure_time")


def test_describe_params_исключение_хука_bindings_отвечает_отказом_а_не_исключением(make):
    rig = make()
    _take(rig)

    def broken():
        raise RuntimeError("хук")

    rig.plugin.bindings = broken
    base = len(rig.port.calls)
    assert _call(lambda: rig.plugin.cmd_describe_params({})) == {"success": False, "error": "RuntimeError"}
    assert "describe_param" not in rig.names(base)


# -- фейк: замок refs -----------------------------------------------------------------------------------------------


def test_refs_фейка_не_теряет_счёт_при_параллельных_acquire_release():
    sdk = make_port().sdk
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # чаще переключения потоков: без замка `+= 1` теряет обновления
    try:
        gate = threading.Event()

        def hammer() -> None:
            gate.wait(2.0)
            for _ in range(3000):
                sdk.acquire()
                sdk.release()

        threads = [_bg(hammer) for _ in range(6)]
        gate.set()
        for worker, box in threads:
            _join(worker, box, deadline=30.0)
    finally:
        sys.setswitchinterval(old_interval)
    assert sdk.refs == 0
