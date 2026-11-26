# -*- coding: utf-8 -*-
"""Приёмка Task 2.3d вслепую: команды прибора плагина — `list_devices`, `describe_params`, `trigger_software`.

Настоящий `CameraDevicePlugin` + фейк порта (плагин с монкейпатчем `create_port`, как в `test_slice_plugin.py`) +
настоящий `WorkerManager`. Проверяется наблюдаемое: ответ команды, журнал порта (`FakePort.calls`: имя, аргументы,
поток), счётчики `sdk.refs` и `create_port`. Ожидаемые значения — литералы (таблицы фейка `fake_port.py`).
Любой вызов, который может зависнуть, идёт в daemon-потоке с дедлайном `join`; ожидания эффектов — с дедлайном.
Hazard-тесты (`call` против `stop`, медленный `close`, сторож `call`) пишет автор кода в других файлах.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import Binding, PortError
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing.fake_port import ALL_CAPABILITIES, make_port

pytestmark = pytest.mark.timeout(60)

CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}
LISTED = {"success": True, "devices": [{"kind": "serial", "value": "FAKE-0001", "name": ""}]}
NOT_GRABBING = {"success": False, "error": "сеанс не в захвате"}
NO_NODE_DESCRIBE = ALL_CAPABILITIES - {"node_describe"}
BRIDGE_LOGGER = "camera_device.session"


class _OtherTriggerPlugin(CameraDevicePlugin):
    """Подкласс вендора: программный триггер — узел, которого фейк не знает."""

    def software_trigger_binding(self) -> Binding:
        return Binding("genicam", "Other", "command")


class _Rig:
    """Плагин + фейк порта + менеджер воркеров; команды зовутся напрямую (`plugin.cmd_*({})`)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, port, plugin_cls=CameraDevicePlugin, **cfg) -> None:
        self.port = port
        self.create_port_calls = 0
        monkeypatch.setattr(plugin_base, "create_port", self._create_port)
        config = {**CFG, **cfg}
        services = MockProcessServices(name="cam_cmds", config=config)
        self.wm = WorkerManager("test_cam_cmds")
        services.worker_manager = self.wm  # настоящий менеджер: MockWorkerManager потоков не создаёт
        self.ctx = PluginContext(services=services, config=config)
        self.plugin = plugin_cls()
        self.plugin.configure(self.ctx)

    def _create_port(self, driver: str):
        self.create_port_calls += 1
        return self.port

    def take(self) -> dict:
        result = _call(lambda: self.plugin.cmd_take_device({}))
        assert result["status"] == "ok", result
        return result

    def command(self, name: str) -> dict:
        """Команда плагина по имени из `commands`, в daemon-потоке с дедлайном."""
        return _call(lambda: getattr(self.plugin, f"cmd_{name}")({}))

    def names(self, start: int = 0, skip: tuple[str, ...] = ("get_frame",)) -> list[str]:
        return [name for name, _args, _tid in self.port.calls[start:] if name not in skip]

    def open_thread(self) -> int:
        return next(tid for name, _args, tid in self.port.calls if name == "open")

    def close(self) -> None:
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(port=None, **kwargs) -> _Rig:
        rig = _Rig(monkeypatch, port if port is not None else make_port(frame_period_s=0.02), **kwargs)
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        rig.close()


def _call(fn, deadline: float = 8.0):
    """`fn` в daemon-потоке; не вернулся за `deadline` — тест падает; исключение `fn` летит в тест."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение отдаётся тесту
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline)
    assert not thread.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box["result"]


def _await(predicate, what: str, deadline: float = 3.0) -> None:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail(f"за {deadline} с не случилось: {what}")


def _count(rig: _Rig, name: str) -> int:
    return sum(1 for call in list(rig.port.calls) if call[0] == name)


def _bridges() -> list:
    return [h for h in logging.getLogger(BRIDGE_LOGGER).handlers if type(h).__name__ == "_SessionLogBridge"]


# ---------------------------------------------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------------------------------------------


def test_list_devices_без_сеанса_отвечает_списком_приборов(make):
    rig = make()
    assert rig.command("list_devices") == LISTED


def test_list_devices_без_сеанса_журнал_порта_acquire_enum_release_без_open(make):
    rig = make()
    rig.command("list_devices")
    assert [name for name, _args, _tid in rig.port.calls] == ["acquire", "enum_devices", "release"]


def test_list_devices_без_сеанса_не_оставляет_ссылку_на_sdk(make):
    rig = make()
    rig.command("list_devices")
    assert rig.port.sdk.refs == 0


def test_list_devices_без_сеанса_не_создаёт_сеанс_и_не_ставит_мост_логов(make):
    bridges_before = _bridges()
    rig = make()
    rig.command("list_devices")
    assert rig.plugin._session is None
    assert rig.plugin._log_bridge is None
    assert _bridges() == bridges_before
    rig.take()  # контроль: настоящий take_device мост ставит, проверка выше не вакуумна
    assert len(_bridges()) == len(bridges_before) + 1


def test_list_devices_дважды_и_take_device_используют_один_порт(make):
    rig = make()
    rig.command("list_devices")
    rig.command("list_devices")
    rig.take()
    assert rig.create_port_calls == 1
    assert rig.port.sdk.refs == 1, "acquire/release list_devices не сбалансированы или take_device не взял SDK"
    assert _count(rig, "open") == 1


def test_list_devices_при_захвате_отвечает_тем_же_списком(make):
    rig = make()
    rig.take()
    assert rig.command("list_devices") == LISTED


def test_list_devices_при_захвате_в_журнале_только_enum_devices_без_acquire_и_release(make):
    rig = make()
    rig.take()
    base = len(rig.port.calls)
    rig.command("list_devices")
    assert rig.names(base) == ["enum_devices"]


def test_list_devices_при_захвате_enum_devices_идёт_в_потоке_владельца(make):
    rig = make()
    rig.take()
    base = len(rig.port.calls)
    rig.command("list_devices")
    enum_threads = [tid for name, _args, tid in rig.port.calls[base:] if name == "enum_devices"]
    assert enum_threads == [rig.open_thread()]
    assert threading.get_ident() not in enum_threads


def test_list_devices_при_захвате_ссылка_sdk_одна_до_и_после_кадры_идут(make):
    rig = make()
    rig.take()
    assert rig.port.sdk.refs == 1
    rig.command("list_devices")
    assert rig.port.sdk.refs == 1
    frames = _count(rig, "get_frame")
    _await(lambda: _count(rig, "get_frame") >= frames + 3, "кадры продолжают идти после list_devices")


def test_list_devices_при_opening_отказывает_и_порт_не_вызван(make):
    rig = make(make_port(open_delay_s=0.3, frame_period_s=0.02))
    taker = threading.Thread(target=lambda: rig.plugin.cmd_take_device({}), daemon=True)
    taker.start()
    _await(lambda: _count(rig, "open") == 1, "владелец вошёл в open")
    base = len(rig.port.calls)
    result = rig.command("list_devices")
    assert rig.plugin.cmd_get_status({})["state"] == "opening", "окно opening закрылось раньше проверки"
    assert result == NOT_GRABBING
    assert len(rig.port.calls) == base, rig.port.calls[base:]
    taker.join(5.0)
    assert not taker.is_alive()


def test_list_devices_при_stopping_отказывает_и_порт_не_вызван(make):
    rig = make()
    rig.take()
    rig.port.arm_hang(0.8)  # следующий get_frame держит владельца: окно `stopping` длится ~0,8 с
    time.sleep(0.1)
    stopper = threading.Thread(target=lambda: rig.plugin.cmd_release_device({}), daemon=True)
    stopper.start()
    _await(lambda: rig.plugin.cmd_get_status({})["state"] == "stopping", "сеанс вошёл в stopping")
    base = len(rig.port.calls)
    result = rig.command("list_devices")
    assert rig.plugin.cmd_get_status({})["state"] == "stopping", "окно stopping закрылось раньше проверки"
    assert result == NOT_GRABBING
    assert len(rig.port.calls) == base, rig.port.calls[base:]
    stopper.join(5.0)
    assert not stopper.is_alive()


# ---------------------------------------------------------------------------------------------------------------
# describe_params
# ---------------------------------------------------------------------------------------------------------------


def test_describe_params_при_захвате_exposure_time_по_таблице_фейка(make):
    rig = make()
    rig.take()
    result = rig.command("describe_params")
    assert result["success"] is True, result
    assert result["params_meta"]["exposure_time"] == {
        "min": 6.0,
        "max": 9999746.0,
        "inc": 1.0,
        "entries": None,
        "access": "RW",
    }


def test_describe_params_при_захвате_есть_все_поля_привязок(make):
    rig = make()
    rig.take()
    meta = rig.command("describe_params")["params_meta"]
    assert set(meta) >= {"trigger_mode", "trigger_source", "trigger_period_ms", "exposure_time"}
    assert all(meta[field] is not None for field in ("trigger_mode", "trigger_source", "trigger_period_ms"))


def test_describe_params_при_захвате_trigger_mode_entries_список_и_доступ_ro(make):
    rig = make()
    rig.take()
    meta = rig.command("describe_params")["params_meta"]
    assert meta["trigger_mode"]["entries"] == ["Off", "On"]
    assert isinstance(meta["trigger_mode"]["entries"], list)
    assert meta["trigger_mode"]["access"] == "RO"


def test_describe_params_каждый_describe_param_идёт_в_потоке_владельца(make):
    rig = make()
    rig.take()
    base = len(rig.port.calls)
    rig.command("describe_params")
    threads = [tid for name, _args, tid in rig.port.calls[base:] if name == "describe_param"]
    assert threads, "команда не вызвала describe_param"
    assert set(threads) == {rig.open_thread()}


def test_describe_params_вызывает_describe_param_ровно_по_разу_на_привязку(make):
    rig = make()
    rig.take()
    base = len(rig.port.calls)  # ProfileRunner._step_of уже звал describe_param при открытии: считаем с этой отметки
    rig.command("describe_params")
    keys = sorted(args[0] for name, args, _tid in rig.port.calls[base:] if name == "describe_param")
    assert keys == ["ExposureTime", "TriggerMode", "TriggerSelfTriggerPeriod", "TriggerSource"]


def test_describe_params_без_node_describe_пустая_карта_и_порт_не_вызван_при_захвате(make):
    rig = make(make_port(capabilities=NO_NODE_DESCRIBE, frame_period_s=0.02))
    rig.take()
    base = len(rig.port.calls)
    result = rig.command("describe_params")
    assert result == {"success": True, "params_meta": {}}
    assert "describe_param" not in rig.names(base)


def test_describe_params_без_node_describe_и_без_захвата_пустая_карта_порт_не_вызван(make):
    rig = make(make_port(capabilities=NO_NODE_DESCRIBE))
    result = rig.command("describe_params")
    assert result == {"success": True, "params_meta": {}}
    assert rig.port.calls == []


def test_describe_params_отказ_узла_даёт_none_для_поля_остальные_заполнены(make):
    rig = make()
    rig.take()
    original = rig.port.describe_param

    def flaky(binding):
        if binding.key == "ExposureTime":
            raise PortError("other", "describe_param")
        return original(binding)

    rig.port.describe_param = flaky  # без подмены фейк бросает только на неизвестный ключ или закрытый порт
    result = rig.command("describe_params")
    assert result["success"] is True, result
    meta = result["params_meta"]
    assert meta["exposure_time"] is None
    assert meta["trigger_mode"]["entries"] == ["Off", "On"]
    assert meta["trigger_source"] is not None
    assert meta["trigger_period_ms"] is not None


def test_describe_params_без_захвата_с_capability_отказывает(make):
    rig = make()
    assert rig.command("describe_params") == NOT_GRABBING
    assert "describe_param" not in rig.names()


# ---------------------------------------------------------------------------------------------------------------
# trigger_software
# ---------------------------------------------------------------------------------------------------------------


def test_trigger_software_без_capability_отказывает_и_сеанс_не_создан(make):
    rig = make(make_port(capabilities=frozenset()))
    result = rig.command("trigger_software")
    assert result == {"success": False, "error": "нет capability software_trigger"}
    assert "execute" not in rig.names()
    assert rig.plugin._session is None


def test_trigger_software_с_capability_без_захвата_отказывает(make):
    rig = make()
    assert rig.command("trigger_software") == NOT_GRABBING
    assert "execute" not in rig.names()


def test_trigger_software_при_захвате_успех(make):
    rig = make()
    rig.take()
    assert rig.command("trigger_software") == {"success": True}


def test_trigger_software_при_захвате_execute_triggersoftware_в_потоке_владельца(make):
    rig = make()
    rig.take()
    base = len(rig.port.calls)
    rig.command("trigger_software")
    executes = [(args, tid) for name, args, tid in rig.port.calls[base:] if name == "execute"]
    assert executes == [(("TriggerSoftware",), rig.open_thread())]


# ---------------------------------------------------------------------------------------------------------------
# хук software_trigger_binding
# ---------------------------------------------------------------------------------------------------------------


def test_хук_software_trigger_binding_команда_берёт_привязку_из_хука(make):
    rig = make(plugin_cls=_OtherTriggerPlugin)
    rig.take()
    base = len(rig.port.calls)
    result = rig.command("trigger_software")
    assert result["success"] is False, result  # фейк отказывает чужому ключу
    executes = [args for name, args, _tid in rig.port.calls[base:] if name == "execute"]
    assert executes == [("Other",)]


# ---------------------------------------------------------------------------------------------------------------
# набор команд
# ---------------------------------------------------------------------------------------------------------------

NINE = {
    "take_device",
    "release_device",
    "get_status",
    "reset_stats",
    "read_params",
    "apply_params",
    "list_devices",
    "describe_params",
    "trigger_software",
    "trigger_seen",
}


def test_набор_команд_плагина_девять_команд_р7():
    assert set(CameraDevicePlugin.commands) == NINE


def test_набор_команд_вместе_с_set_config_и_register_update_одиннадцать_для_4_2a():
    assert set(CameraDevicePlugin.commands) | {"set_config", "register_update"} == NINE | {
        "set_config",
        "register_update",
    }
    assert len(NINE | {"set_config", "register_update"}) == 12


def test_каждая_команда_из_набора_указывает_на_существующий_метод():
    for command, method in CameraDevicePlugin.commands.items():
        assert callable(getattr(CameraDevicePlugin, method, None)), f"{command} -> {method}"


def test_регистрация_команд_плагином_отдаёт_девять_и_generic_set_config(make):
    rig = make()
    rig.plugin._auto_register_commands(rig.ctx)
    registered = rig.ctx.command_manager.commands
    assert set(registered) == NINE | {"set_config"}
    assert _call(lambda: registered["list_devices"]({})) == LISTED


# ---------------------------------------------------------------------------------------------------------------
# страж: плагин не создаёт потоков сам
# ---------------------------------------------------------------------------------------------------------------


def test_страж_plugin_base_не_создаёт_потоков_и_исполнителей():
    """Эквивалент `git grep -nE "threading\\.Thread|KeyedExecutor|ThreadPoolExecutor" -- plugin_base.py`: пусто."""
    source = Path(plugin_base.__file__).read_text(encoding="utf-8")
    pattern = re.compile(r"threading\.Thread|KeyedExecutor|ThreadPoolExecutor")
    hits = [f"{n}: {line}" for n, line in enumerate(source.splitlines(), 1) if pattern.search(line)]
    assert hits == []
