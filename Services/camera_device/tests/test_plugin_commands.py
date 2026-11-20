# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 2.3c: команды плагина `reset_stats`, `read_params`, `apply_params` и `commands.py`.

Написаны ДО кода по блоку ACCEPTANCE Task 2.3c и по публичному виду `camera_device` (плагин, сеанс, фейк-порт).
Проверяется наблюдаемое: ответы команд, значения register'а, журнал фейк-порта `port.calls` (без шума
`get_frame`/`describe_param`), вызовы `DeviceSession.start/stop` (шпион на класс — он назван в ACCEPTANCE),
уровни `ctx.publish_metric`. Ожидаемые значения — литералы из ACCEPTANCE.

Проводка `_Rig`: настоящие плагин, `RegistersManager` и `WorkerManager`, фейк только у порта (образец —
`test_live_apply_wiring.py::_Rig`; `PluginOrchestrator` в проводку не входит: `apply_params` зовёт команду плагина
напрямую, а колбэк 2.4b подписан на настоящий `RegistersManager`, поэтому тест не вакуумен).
Форма `apply_params` в тестах — `{"params": {поле: значение}}`; короткая запись «{"exposure_time": 901.0}» в ACCEPTANCE
понята как содержимое `params` (при `extra=forbid` на верхнем уровне плоская форма невозможна, см. отчёт).
Тесты, зависящие от ещё не существующих `commands.py`, `cmd_reset_stats`, `cmd_read_params`, `cmd_apply_params`,
красные до кода; тесты `seq_id`, `start(5.0)`, `stop(2.0)` и страж потоков — контроль, зелёные до кода.
Вызов, который может заблокироваться, идёт в daemon-потоке с дедлайном.
"""

from __future__ import annotations

import importlib
import re
import threading
import time
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import ValidationError

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import Binding, RawFrame
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.session import DeviceSession
from Services.camera_device.testing.fake_port import FAKE_BINDINGS, make_port

pytestmark = pytest.mark.timeout(60)

REG = "camera_device"
CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}
_NOISE = frozenset({"get_frame", "describe_param"})
REPO_ROOT = Path(__file__).resolve().parents[3]
CAMERA_DIR = REPO_ROOT / "Services" / "camera_device"


# ---------------------------------------------------------------------------------------------- #
# Каркас
# ---------------------------------------------------------------------------------------------- #


def _bounded(fn, seconds: float = 10.0):
    """Вызов в daemon-потоке с дедлайном: зависшая команда не вешает набор; исключение вызова пробрасывается."""
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


class _CfgRegisters(CameraDeviceRegisters):
    """Register с полем политики `config` (узел фейка существует, при `trigger_managed=False` не пишется)."""

    trigger_period_ms: Annotated[
        int,
        FieldMeta("Период самотриггера, мс", apply="config"),
    ] = 40


class _CfgPlugin(CameraDevicePlugin):
    register_class = _CfgRegisters


class _ReadonlyBoundPlugin(CameraDevicePlugin):
    """`bindings()` дополнен `frames` (readonly в register'е)."""

    def bindings(self) -> dict[str, Binding]:
        return {**FAKE_BINDINGS, "frames": Binding("genicam", "Frames", "int")}


class _Rig:
    """Настоящий плагин + `RegistersManager` (или без него) + настоящий `WorkerManager` + фейк порта."""

    def __init__(
        self,
        monkeypatch,
        port=None,
        *,
        plugin_cls=CameraDevicePlugin,
        reg_cls=CameraDeviceRegisters,
        with_registers: bool = True,
    ) -> None:
        self.port = port if port is not None else make_port(frame_period_s=0.02)
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: self.port)
        self.services = MockProcessServices(name="cam_cmd", config=dict(CFG))
        self.wm = WorkerManager("test_cam_cmd")
        self.services.worker_manager = self.wm
        self.rm = RegistersManager(registers={REG: reg_cls()}) if with_registers else None
        self.ctx = PluginContext(services=self.services, config=dict(CFG), registers=self.rm, plugin_name=REG)
        self.published: list[tuple[str, object]] = []
        publish = self.ctx.publish_metric
        self.ctx.publish_metric = lambda name, value: (self.published.append((name, value)), publish(name, value))[0]
        self.plugin = plugin_cls()
        self.plugin.configure(self.ctx)

    @property
    def reg(self):
        """Register, как его видит GUI (managed), иначе локальный экземпляр плагина."""
        return self.rm.get_register(REG) if self.rm is not None else self.plugin._reg

    def take(self, data: dict | None = None) -> dict:
        return _bounded(lambda: self.plugin.cmd_take_device(data or {}))

    def release(self, data: dict | None = None) -> dict:
        return _bounded(lambda: self.plugin.cmd_release_device(data or {}))

    def command(self, name: str, data: dict) -> dict:
        return _bounded(lambda: getattr(self.plugin, f"cmd_{name}")(data))

    def apply(self, params: dict, **extra) -> dict:
        return self.command("apply_params", {"params": params, **extra})

    def status(self) -> dict:
        return self.plugin.cmd_get_status({})

    def journal(self, start: int = 0) -> list[tuple]:
        return [(name, args) for name, args, _ in self.port.calls[start:] if name not in _NOISE]

    def close(self) -> None:
        if getattr(self.plugin, "_session", None) is not None:
            self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(port=None, **kwargs) -> _Rig:
        rig = _Rig(monkeypatch, port, **kwargs)
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        rig.close()


def _wait(predicate, what: str, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(f"за {timeout} с не случилось: {what}")


def _wait_wrote(rig: _Rig, start: int, value: float) -> None:
    _wait(lambda: ("set_param", ("ExposureTime", value)) in rig.journal(start), f"set_param(ExposureTime, {value})")


def _session_spy(monkeypatch, name: str) -> list:
    """Шпион на `DeviceSession.<name>`: записывает первый аргумент (срок), вызов передаёт настоящему методу."""
    calls: list = []
    original = getattr(DeviceSession, name)

    def spy(self, *args, **kwargs):
        calls.append(args[0] if args else (next(iter(kwargs.values())) if kwargs else None))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DeviceSession, name, spy)
    return calls


def _feed(plugin: CameraDevicePlugin, number: int, pixel_format: str = "mono8") -> list[dict]:
    """Кадр от сеанса (`_on_frame`) и один `produce()`."""
    plugin._on_frame(RawFrame(bytearray(range(8)), 4, 2, pixel_format, number))
    return plugin.produce()


def _commands_module():
    return importlib.import_module("Services.camera_device.commands")


# ---------------------------------------------------------------------------------------------- #
# Контракт commands.py
# ---------------------------------------------------------------------------------------------- #


def test_commands_all_ровно_три_модели():
    assert _commands_module().__all__ == ["ApplyParamsArgs", "ReleaseDeviceArgs", "TakeDeviceArgs"]


def test_commands_сроки_по_умолчанию():
    commands = _commands_module()
    assert commands.TakeDeviceArgs().timeout_s == 5.0
    assert commands.ReleaseDeviceArgs().timeout_s == 2.0


@pytest.mark.parametrize("model", ["TakeDeviceArgs", "ReleaseDeviceArgs"])
@pytest.mark.parametrize("bad", [0, -1, 30.1])
def test_commands_срок_вне_границ_отклоняется(model, bad):
    with pytest.raises(ValidationError):
        getattr(_commands_module(), model)(timeout_s=bad)


@pytest.mark.parametrize("model", ["TakeDeviceArgs", "ReleaseDeviceArgs"])
@pytest.mark.parametrize("good", [30.0, 0.5])
def test_commands_срок_на_границе_принимается(model, good):
    assert getattr(_commands_module(), model)(timeout_s=good).timeout_s == good


def test_commands_apply_params_лишнее_поле_отклоняется():
    with pytest.raises(ValidationError):
        _commands_module().ApplyParamsArgs(params={}, x=1)


# ---------------------------------------------------------------------------------------------- #
# take_device / release_device: срок идёт в сеанс
# ---------------------------------------------------------------------------------------------- #


def test_take_device_срок_из_аргумента_доходит_до_start(make, monkeypatch):
    starts = _session_spy(monkeypatch, "start")
    rig = make()
    assert rig.take({"timeout_s": 0.5})["status"] == "ok"
    assert starts == [0.5]


def test_take_device_без_срока_start_5_секунд(make, monkeypatch):
    starts = _session_spy(monkeypatch, "start")
    rig = make()
    assert rig.take({})["status"] == "ok"
    assert starts == [5.0]


def test_release_device_срок_из_аргумента_доходит_до_stop(make, monkeypatch):
    stops = _session_spy(monkeypatch, "stop")
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.release({"timeout_s": 0.7})
    assert stops[0] == 0.7, stops


def test_release_device_без_срока_stop_2_секунды(make, monkeypatch):
    stops = _session_spy(monkeypatch, "stop")
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.release({})
    assert stops[0] == 2.0, stops


def test_take_device_срок_3600_отклоняется_и_start_не_вызван(make, monkeypatch):
    starts = _session_spy(monkeypatch, "start")
    rig = make()
    result = rig.take({"timeout_s": 3600})
    assert result["status"] == "error", result
    assert starts == []


# ---------------------------------------------------------------------------------------------- #
# read_params
# ---------------------------------------------------------------------------------------------- #


def test_read_params_до_take_device_пустой_снимок(make):
    rig = make()
    assert rig.command("read_params", {}) == {"success": True, "params": {}, "param_errors": {}}


def test_read_params_после_take_device_значения_прибора(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    assert rig.command("read_params", {}) == {
        "success": True,
        "params": {"exposure_time": 10000.0},
        "param_errors": {},
    }


def test_read_params_после_release_device_тот_же_снимок(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.release()
    assert rig.command("read_params", {}) == {
        "success": True,
        "params": {"exposure_time": 10000.0},
        "param_errors": {},
    }


def test_read_params_не_трогает_порт(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    before = len(rig.journal())
    rig.command("read_params", {})
    assert len(rig.journal()) == before, "read_params дошёл до порта (за вычетом шума get_frame/describe_param)"
    rig.release()
    raw_before = len(rig.port.calls)  # порт закрыт, поток чтения остановлен: журнал стоит
    result = rig.command("read_params", {})
    assert result["success"] is True, "ответ после release_device нужен, чтобы сравнение было не вхолостую"
    assert len(rig.port.calls) == raw_before, "read_params дописал в журнал порта"


# ---------------------------------------------------------------------------------------------- #
# reset_stats
# ---------------------------------------------------------------------------------------------- #


def test_контроль_seq_id_растёт_по_кадрам(make):
    plugin = make().plugin
    seqs = [_feed(plugin, number)[0]["seq_id"] for number in range(1, 6)]
    assert seqs == [1, 2, 3, 4, 5]


def test_reset_stats_обнуляет_счётчики_и_публикует_ноль(make):
    rig = make()
    plugin = rig.plugin
    for number in range(1, 4):
        _feed(plugin, number)
    plugin._tick_t0 = time.monotonic() - plugin_base._TICK_S  # окно с тремя кадрами: `_tick_frames` не ноль
    _feed(plugin, 4)
    _feed(plugin, 5)
    assert rig.reg.frames == 5
    assert rig.status()["frames"] == 5
    mark = len(rig.published)

    result = rig.command("reset_stats", {})

    assert result == {"success": True}
    assert rig.status()["frames"] == 0
    assert rig.reg.frames == 0
    assert ("frames", 0) in rig.published[mark:], rig.published[mark:]
    mark = len(rig.published)
    plugin._tick_t0 = time.monotonic() - plugin_base._TICK_S  # следующее окно
    assert plugin.produce() == []
    window = rig.published[mark:]
    fps = [value for name, value in window if name == "fps"]
    assert fps and fps[-1] >= 0, f"fps после сброса отрицателен или не опубликован: {window}"
    assert [value for name, value in window if name == "dropped"] == [0]


def test_reset_stats_обнуляет_dropped_после_битого_кадра(make):
    rig = make()
    plugin = rig.plugin
    assert _feed(plugin, 1, "weird_fmt") == []
    plugin._tick_t0 = time.monotonic() - plugin_base._TICK_S
    plugin.produce()
    assert ("dropped", 1) in rig.published, (
        "до сброса окно должно показать 1 отброшенный кадр (иначе проверка вхолостую)"
    )
    mark = len(rig.published)

    assert rig.command("reset_stats", {}) == {"success": True}
    plugin._tick_t0 = time.monotonic() - plugin_base._TICK_S
    plugin.produce()

    assert [value for name, value in rig.published[mark:] if name == "dropped"] == [0]


def test_reset_stats_seq_id_не_сбрасывается_следующий_шестой(make):
    rig = make()
    plugin = rig.plugin
    for number in range(1, 6):
        _feed(plugin, number)

    assert rig.command("reset_stats", {}) == {"success": True}

    items = _feed(plugin, 6)
    assert [item["seq_id"] for item in items] == [6]


def test_reset_stats_битый_кадр_тоже_имеет_номер_следующий_седьмой(make):
    rig = make()
    plugin = rig.plugin
    for number in range(1, 6):
        _feed(plugin, number)
    assert _feed(plugin, 6, "weird_fmt") == []

    assert rig.command("reset_stats", {}) == {"success": True}

    items = _feed(plugin, 7)
    assert [item["seq_id"] for item in items] == [7]


def test_reset_stats_снимает_last_error_битого_кадра(make):
    rig = make()
    plugin = rig.plugin
    assert _feed(plugin, 1, "weird_fmt") == []
    assert rig.status()["last_error"] != "", "битый кадр должен оставить причину (иначе проверка вхолостую)"

    assert rig.command("reset_stats", {}) == {"success": True}

    assert rig.status()["last_error"] == ""


# ---------------------------------------------------------------------------------------------- #
# apply_params: проводка с настоящим RegistersManager
# ---------------------------------------------------------------------------------------------- #

APPLIED = {"success": True, "applied": ["exposure_time"]}


def test_apply_params_до_take_device_пишет_register_без_прибора(make):
    rig = make()
    result = rig.apply({"exposure_time": 900.0})
    assert result == {**APPLIED, "on_device": False}
    assert rig.reg.exposure_time == 900.0
    assert rig.port.calls == [], "порт тронут до take_device"


def test_apply_params_при_захвате_доходит_до_журнала_фейка(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    result = rig.apply({"exposure_time": 900.0})

    assert result == {**APPLIED, "on_device": True}
    expected = [("set_param", ("ExposureTime", 900.0)), ("get_param", ("ExposureTime",))]
    _wait(lambda: len(rig.journal(base)) >= 2, "запись и обратное чтение узла")  # запись идёт ~24 мс после ответа
    assert rig.journal(base) == expected
    assert rig.reg.exposure_time == 900.0


def test_apply_params_неизвестное_поле_пакет_не_применяется(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    result = rig.apply({"exposure_time": 900.0, "nope": 1})

    assert result == {"success": False, "error": "поле не параметр прибора: 'nope'"}
    assert rig.reg.exposure_time == 10000.0
    # контроль не вакуумный: следующая правка доходит до журнала, значит подписка жива, а 900.0 не пришёл раньше неё
    assert rig.apply({"exposure_time": 901.0})["success"] is True
    _wait_wrote(rig, base, 901.0)
    assert [call for call in rig.journal(base) if call[0] == "set_param"] == [("set_param", ("ExposureTime", 901.0))]


@pytest.mark.parametrize(
    ("field", "value", "before"),
    [("timeout_ms", 900, 500), ("trigger_managed", True, False)],
)
def test_apply_params_поле_вне_bindings_отклоняется(make, field, value, before):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    result = rig.apply({field: value})

    assert result["success"] is False, result
    assert getattr(rig.reg, field) == before
    assert rig.apply({"exposure_time": 903.0})["success"] is True  # контроль: подписка жива
    _wait_wrote(rig, base, 903.0)
    assert [call for call in rig.journal(base) if call[0] == "set_param"] == [("set_param", ("ExposureTime", 903.0))]


def test_apply_params_смешанный_пакет_с_неверным_значением_не_применяется_и_не_течёт(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    result = rig.apply({"exposure_time": 900.0, "trigger_mode": "SECRET-42"})

    assert result["success"] is False, result
    assert "SECRET-42" not in str(result.get("error", ""))
    assert rig.reg.exposure_time == 10000.0
    assert rig.apply({"exposure_time": 902.0})["success"] is True  # контроль: следующий корректный пакет доходит
    _wait_wrote(rig, base, 902.0)
    assert [call for call in rig.journal(base) if call[0] == "set_param"] == [("set_param", ("ExposureTime", 902.0))]


def test_apply_params_политика_config_прибор_не_трогает_а_live_пишет(make):
    rig = make(reg_cls=_CfgRegisters, plugin_cls=_CfgPlugin)
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    result = rig.apply({"trigger_period_ms": 60})

    assert result == {"success": True, "applied": ["trigger_period_ms"], "on_device": False}
    assert rig.reg.trigger_period_ms == 60
    live = rig.apply({"exposure_time": 905.0})
    assert live == {**APPLIED, "on_device": True}
    _wait_wrote(rig, base, 905.0)
    assert [call for call in rig.journal(base) if call[0] == "set_param"] == [("set_param", ("ExposureTime", 905.0))], (
        "поле с apply=config дошло до прибора"
    )


def test_apply_params_readonly_поле_из_bindings_отклоняется(make):
    rig = make(plugin_cls=_ReadonlyBoundPlugin)

    result = rig.apply({"frames": 5})

    assert result == {"success": False, "error": "поле только для чтения: frames"}
    assert rig.reg.frames == 0


def test_apply_params_без_registers_manager_отказ(make):
    rig = make(with_registers=False)
    assert rig.apply({"exposure_time": 900.0}) == {"success": False, "error": "нет RegistersManager"}


def test_apply_params_пустой_params_успех_без_изменений(make):
    rig = make()
    assert rig.apply({}) == {"success": True, "applied": [], "on_device": False}
    assert rig.reg.exposure_time == 10000.0


def test_apply_params_лишний_ключ_верхнего_уровня_отклоняется_и_не_течёт(make):
    rig = make()

    result = rig.command("apply_params", {"params": {"exposure_time": 1}, "token": "SECRET-42"})

    assert result["success"] is False, result
    assert "SECRET-42" not in str(result.get("error", ""))
    assert rig.reg.exposure_time == 10000.0


def test_apply_params_значение_неверного_типа_отклоняется(make):
    rig = make()

    result = rig.apply({"exposure_time": "abc"})

    assert result["success"] is False, result
    assert rig.reg.exposure_time == 10000.0


# ---------------------------------------------------------------------------------------------- #
# Страж: никаких новых потоков и ровно шесть команд
# ---------------------------------------------------------------------------------------------- #

_THREAD_PATTERN = re.compile(r"threading\.Thread|KeyedExecutor|ThreadPoolExecutor")


def test_страж_плагин_и_commands_не_создают_потоков():
    """Регэксп (не `git grep`: до коммита `commands.py` неотслеживаем) по файлам; `commands.py` — если уже есть."""
    plugin_text = (CAMERA_DIR / "plugin_base.py").read_text(encoding="utf-8")
    assert re.search(r"class CameraDevicePlugin", plugin_text), "контроль: файл прочитан, регэксп видит класс"
    files = [CAMERA_DIR / "plugin_base.py"]
    if (CAMERA_DIR / "commands.py").exists():
        files.append(CAMERA_DIR / "commands.py")
    found = [
        f"{path.name}:{number}: {line.strip()}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _THREAD_PATTERN.search(line)
    ]
    assert found == []


def test_страж_набор_команд_плагина_девять_команд_р7():
    # 2.3c: три прежних + reset_stats, read_params, apply_params; 2.3d: list_devices, describe_params, trigger_software
    expected = {
        "take_device": "cmd_take_device",
        "release_device": "cmd_release_device",
        "get_status": "cmd_get_status",
        "reset_stats": "cmd_reset_stats",
        "read_params": "cmd_read_params",
        "apply_params": "cmd_apply_params",
        "list_devices": "cmd_list_devices",
        "describe_params": "cmd_describe_params",
        "trigger_software": "cmd_trigger_software",
    }
    assert CameraDevicePlugin.commands == expected
    # собственные атрибуты класса: унаследованный от базы `cmd_set_config` в набор плагина не входит
    assert {name for name in vars(CameraDevicePlugin) if name.startswith("cmd_")} == set(expected.values())
    assert all(callable(getattr(CameraDevicePlugin, attr)) for attr in expected.values())
