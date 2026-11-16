# -*- coding: utf-8 -*-
"""Хазард-тесты Task 2.3c (автор): гонка `reset_stats` с `produce()`, дисциплина замка статистики, порядок проверок и
запись `apply_params`, срок `take_device`/`release_device`.

Файл БЕЗ `from __future__ import annotations`: аннотации register-класса подкласса должны быть настоящими объектами.
Всё, что может зависнуть, идёт в daemon-потоке с дедлайном. Ожидаемые значения — литералы.
Контракт `commands.py` и приёмка команд лежат в слепом `test_plugin_commands.py` и здесь не дублируются.
"""

import threading
import time
from typing import Annotated

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta
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


class _GainRegisters(CameraDeviceRegisters):
    """Register с привязанным полем, которое меняется только с уровнем доступа 1 (проба на копии прав не проверяет)."""

    gain: Annotated[float, FieldMeta("Усиление", access_level=1, apply="live")] = 1.0


class _GainPlugin(CameraDevicePlugin):
    register_class = _GainRegisters

    def bindings(self) -> dict[str, Binding]:
        return {**FAKE_BINDINGS, "gain": Binding("genicam", "Gain", "float")}


class _ReadonlyBoundPlugin(CameraDevicePlugin):
    """`bindings()` дополнен `frames` (readonly в register'е)."""

    def bindings(self) -> dict[str, Binding]:
        return {**FAKE_BINDINGS, "frames": Binding("genicam", "Frames", "int")}


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


def _wait(predicate, what: str, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(f"за {timeout} с не случилось: {what}")


class _Rig:
    """Настоящие плагин, `RegistersManager` (или без него) и `WorkerManager`; фейк только у порта."""

    def __init__(
        self, monkeypatch, *, plugin_cls=CameraDevicePlugin, reg_cls=CameraDeviceRegisters, with_registers: bool = True
    ) -> None:
        self.port = make_port(frame_period_s=0.02)
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: self.port)
        services = MockProcessServices(name="cam_haz", config=dict(CFG))
        self.wm = WorkerManager("test_cam_haz")
        services.worker_manager = self.wm
        self.rm = RegistersManager(registers={REG: reg_cls()}) if with_registers else None
        self.ctx = PluginContext(services=services, config=dict(CFG), registers=self.rm, plugin_name=REG)
        self.plugin = plugin_cls()
        self.plugin.configure(self.ctx)

    @property
    def reg(self):
        return self.rm.get_register(REG)

    def apply(self, params: dict) -> dict:
        return _bounded(lambda: self.plugin.cmd_apply_params({"params": params}))

    def journal(self, start: int = 0) -> list[tuple]:
        return [(name, args) for name, args, _ in self.port.calls[start:] if name not in _NOISE]

    def writes(self, start: int = 0) -> list[tuple]:
        return [call for call in self.journal(start) if call[0] == "set_param"]

    def spy_writes(self) -> list[tuple]:
        """Шпион на `RegistersManager.set_field_value`: список `(register, поле, значение)`; вызов идёт настоящему."""
        seen: list[tuple] = []
        original = self.rm.set_field_value

        def spy(register, field, value, *args, **kwargs):
            seen.append((register, field, value))
            return original(register, field, value, *args, **kwargs)

        self.rm.set_field_value = spy
        return seen

    def close(self) -> None:
        if getattr(self.plugin, "_session", None) is not None:
            self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(**kwargs) -> _Rig:
        rig = _Rig(monkeypatch, **kwargs)
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        rig.close()


def _good_frame(number: int = 1) -> RawFrame:
    return RawFrame(bytearray(range(8)), 4, 2, "mono8", number)


def _bad_frame(number: int = 1) -> RawFrame:
    return RawFrame(bytearray(range(8)), 4, 2, "weird_fmt", number)


# ---------------------------------------------------------------------------------------------- #
# reset_stats против produce(): замок статистики
# ---------------------------------------------------------------------------------------------- #


class _BlockingFramesReg:
    """Прокси register'а: ПЕРВАЯ запись `frames` блокируется на `Event` (производитель между `+= 1` и записью поля)."""

    def __init__(self, inner, entered: threading.Event, gate: threading.Event) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_entered", entered)
        object.__setattr__(self, "_gate", gate)
        object.__setattr__(self, "_blocked", [False])

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value) -> None:
        if name == "frames" and not self._blocked[0]:
            self._blocked[0] = True
            self._entered.set()
            assert self._gate.wait(10), "ворота не открыли"
        setattr(self._inner, name, value)


def test_reset_stats_ждёт_производителя_между_счётчиком_и_полем_и_итог_сходится(make):
    """С замком `reset_stats` ждёт; без замка он возвращается сразу, и поле (1) расходится со счётчиком (0)."""
    rig = make()
    plugin, inner = rig.plugin, rig.plugin._reg
    entered, gate = threading.Event(), threading.Event()
    plugin._reg = _BlockingFramesReg(inner, entered, gate)
    plugin._on_frame(_good_frame())
    items: list = []
    answers: list = []
    producer = threading.Thread(target=lambda: items.extend(plugin.produce()), daemon=True)
    resetter = threading.Thread(target=lambda: answers.append(plugin.cmd_reset_stats({})), daemon=True)
    try:
        producer.start()
        assert entered.wait(5), "производитель не дошёл до записи поля frames"
        resetter.start()
        resetter.join(0.2)
        assert resetter.is_alive(), "reset_stats вернулся, пока производитель держит пару «счётчик + поле»"
    finally:
        gate.set()
    producer.join(10)
    resetter.join(10)
    assert not producer.is_alive()
    assert not resetter.is_alive()
    assert [item["seq_id"] for item in items] == [1]
    assert answers == [{"success": True}]
    assert inner.frames == 0
    assert plugin.cmd_get_status({})["frames"] == 0


@pytest.mark.parametrize("operation", ["drop_frame", "tick_window", "reset_stats"])
def test_замок_статистики_охраняет_отброс_окно_и_сброс(make, operation):
    """Пока кто-то держит `_stats_lock`, каждая из трёх операций стоит; после освобождения — завершается."""
    rig = make()
    plugin = rig.plugin
    plugin._tick_t0 = time.monotonic() - plugin_base._TICK_S  # окно созрело: `_tick` дойдёт до чтения счётчиков
    actions = {
        "drop_frame": lambda: plugin._drop_frame("причина"),
        "tick_window": plugin._tick,
        "reset_stats": lambda: plugin.cmd_reset_stats({}),
    }
    worker = threading.Thread(target=actions[operation], daemon=True)
    plugin._stats_lock.acquire()
    try:
        worker.start()
        worker.join(0.2)
        assert worker.is_alive(), f"{operation} прошёл мимо замка статистики"
    finally:
        plugin._stats_lock.release()
    worker.join(10)
    assert not worker.is_alive()


def test_публикация_метрик_и_журнал_идут_вне_замка_статистики(make):
    """Замок короткий: `publish_metric` и логи при нём не зовутся (`produce()` при `apply_params` < 50 мс, 4.2a)."""
    rig = make()
    plugin = rig.plugin
    held: list[str] = []

    def watch(kind: str, original):
        def wrapper(*args, **kwargs):
            if plugin._stats_lock.locked():
                held.append(kind)
            return original(*args, **kwargs)

        return wrapper

    rig.ctx.publish_metric = watch("publish_metric", rig.ctx.publish_metric)
    rig.ctx.log_error = watch("log_error", rig.ctx.log_error)
    rig.ctx.log_info = watch("log_info", rig.ctx.log_info)

    plugin._on_frame(_good_frame(1))
    assert len(plugin.produce()) == 1  # publish_metric("frames")
    plugin._on_frame(_bad_frame(2))
    assert plugin.produce() == []  # log_error: новая причина отброса
    assert plugin.cmd_reset_stats({}) == {"success": True}  # publish_metric + log_info
    plugin._tick_t0 = time.monotonic() - plugin_base._TICK_S
    plugin.produce()  # окно: fps/frames/errors/dropped/pending

    assert held == []


# ---------------------------------------------------------------------------------------------- #
# apply_params: порядок проверок, проба на копии, запись по одному, ровно один путь на прибор
# ---------------------------------------------------------------------------------------------- #


def test_apply_params_пишет_поля_в_порядке_словаря(make):
    rig = make()
    seen = rig.spy_writes()

    first = rig.apply({"exposure_time": 900.0, "trigger_period_ms": 50})
    second = rig.apply({"trigger_period_ms": 60, "exposure_time": 901.0})

    assert first == {"success": True, "applied": ["exposure_time", "trigger_period_ms"], "on_device": False}
    assert second == {"success": True, "applied": ["trigger_period_ms", "exposure_time"], "on_device": False}
    assert seen == [
        (REG, "exposure_time", 900.0),
        (REG, "trigger_period_ms", 50),
        (REG, "trigger_period_ms", 60),
        (REG, "exposure_time", 901.0),
    ]


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"exposure_time": 900.0, "nope": 1}, "поле не параметр прибора: 'nope'"),
        ({"exposure_time": 900.0, "trigger_mode": "SECRET-42"}, "trigger_mode: Input should be 'Off' or 'On'"),
        ({"trigger_period_ms": 50, "exposure_time": "abc"}, None),
    ],
)
def test_apply_params_отказ_пробы_не_пишет_ни_одного_поля(make, params, error):
    """Проба идёт на копии: отказ второго поля не оставляет первое ни в register'е, ни в вызовах `set_field_value`."""
    rig = make()
    seen = rig.spy_writes()

    result = rig.apply(params)

    assert result["success"] is False
    if error is not None:
        assert result["error"] == error
    assert "SECRET-42" not in result["error"]
    assert seen == []
    assert rig.reg.exposure_time == 10000.0
    assert rig.reg.trigger_period_ms == 40
    assert rig.reg.trigger_mode == "Off"


def test_apply_params_успешная_проба_не_меняет_register_сама(make):
    """Копия принимает пакет, оригинал меняется только записью `set_field_value`: подмена записи видна сразу."""
    rig = make()
    refuse = {"on": True}
    original = rig.rm.set_field_value

    def gated(register, field, value, *args, **kwargs):
        if refuse["on"]:
            return False, "заперто"
        return original(register, field, value, *args, **kwargs)

    rig.rm.set_field_value = gated

    result = rig.apply({"exposure_time": 900.0})

    assert result == {"success": False, "error": "заперто", "applied": []}
    assert rig.reg.exposure_time == 10000.0  # проба записала только в копию


def test_apply_params_отказ_на_фазе_записи_называет_уже_записанные_поля(make):
    rig = make()
    original = rig.rm.set_field_value
    calls: list[str] = []

    def second_refuses(register, field, value, *args, **kwargs):
        calls.append(field)
        if len(calls) == 2:
            return False, "заперто"
        return original(register, field, value, *args, **kwargs)

    rig.rm.set_field_value = second_refuses

    result = rig.apply({"exposure_time": 900.0, "trigger_period_ms": 50})

    assert result == {"success": False, "error": "заперто", "applied": ["exposure_time"]}
    assert rig.reg.exposure_time == 900.0  # ранее записанное остаётся
    assert rig.reg.trigger_period_ms == 40


def test_apply_params_проверки_идут_в_порядке_модель_registers_bindings_readonly_проба(make):
    plain = make(with_registers=False)
    readonly = make(plugin_cls=_ReadonlyBoundPlugin)

    def call(rig, data):
        return _bounded(lambda: rig.plugin.cmd_apply_params(data))

    # (1) модель раньше (2) registers
    assert call(plain, {"params": {"a": 1}, "token": "SECRET-42"}) == {
        "success": False,
        "error": "token: Extra inputs are not permitted",
    }
    # (2) registers раньше (3) bindings
    assert call(plain, {"params": {"nope": 1}}) == {"success": False, "error": "нет RegistersManager"}
    # (3) bindings (по всему пакету) раньше (4) readonly
    assert call(readonly, {"params": {"frames": 5, "nope": 1}}) == {
        "success": False,
        "error": "поле не параметр прибора: 'nope'",
    }
    # (4) readonly раньше (5) пробы: значение неверного типа не доходит до текста pydantic
    assert call(readonly, {"params": {"frames": "abc"}}) == {
        "success": False,
        "error": "поле только для чтения: frames",
    }
    assert readonly.reg.frames == 0


def test_apply_params_поле_с_уровнем_доступа_отвергается_до_первой_записи(make):
    """`set_field_value` проверяет права (`access_level=0`), проба на копии — нет: пакет не должен писаться частично."""
    rig = make(plugin_cls=_GainPlugin, reg_cls=_GainRegisters)
    seen = rig.spy_writes()

    result = rig.apply({"exposure_time": 900.0, "gain": 2.0})

    assert result == {"success": False, "error": "недостаточно прав для поля: gain"}
    assert seen == []
    assert rig.reg.exposure_time == 10000.0
    assert rig.reg.gain == 1.0


def test_apply_params_пустой_пакет_ничего_не_пишет(make):
    rig = make()
    seen = rig.spy_writes()
    assert rig.apply({}) == {"success": True, "applied": [], "on_device": False}
    assert seen == []


def test_apply_params_на_прибор_ровно_одна_запись_и_один_apply_сеанса(make, monkeypatch):
    """Единственный путь на прибор — колбэк подписки 2.4b: команда `session.apply` не зовёт (удвоение)."""
    applies: list[tuple] = []
    original_apply = DeviceSession.apply

    def spy_apply(self, steps, policy, *args, **kwargs):
        applies.append((tuple(step.field for step in steps), policy))
        return original_apply(self, steps, policy, *args, **kwargs)

    monkeypatch.setattr(DeviceSession, "apply", spy_apply)
    rig = make()
    assert _bounded(lambda: rig.plugin.cmd_take_device({}))["status"] == "ok"
    base = len(rig.port.calls)
    caller: list[int] = []

    result = _bounded(
        lambda: (
            caller.append(threading.get_ident()),
            rig.plugin.cmd_apply_params({"params": {"exposure_time": 900.0}}),
        )[1]
    )

    assert result == {"success": True, "applied": ["exposure_time"], "on_device": True}
    _wait(lambda: rig.writes(base), "set_param на приборе")
    time.sleep(0.3)  # удвоенная запись пришла бы следом; ждём её, а не проверяем «сразу»
    assert rig.writes(base) == [("set_param", ("ExposureTime", 900.0))]
    assert applies == [(("exposure_time",), "live")]
    writer_threads = {thread for name, _, thread in rig.port.calls[base:] if name == "set_param"}
    assert writer_threads and caller[0] not in writer_threads, "порт тронут из потока команды"


def test_apply_params_on_device_ложен_после_release_и_истинен_для_restart(make):
    rig = make()
    assert _bounded(lambda: rig.plugin.cmd_take_device({}))["status"] == "ok"

    restart = rig.apply({"trigger_mode": "On"})  # apply="restart": при захвате колбэк шлёт шаг (если план его меняет)

    assert restart == {"success": True, "applied": ["trigger_mode"], "on_device": True}
    assert _bounded(lambda: rig.plugin.cmd_release_device({}))["status"] == "ok"
    assert rig.apply({"exposure_time": 902.0}) == {"success": True, "applied": ["exposure_time"], "on_device": False}


def test_apply_params_журнал_без_значений_полей(make):
    """INFO `apply_params fields=[…] ok=…` называет поля, но не значения: ни при успехе, ни при отказе."""
    rig = make()
    lines: list[str] = []
    for level in ("log_info", "log_warning", "log_error"):
        setattr(rig.ctx, level, lambda text, *args, **kwargs: lines.append(str(text)))

    assert rig.apply({"exposure_time": 123456.0})["success"] is True
    assert rig.apply({"exposure_time": 777.0, "trigger_mode": "SECRET-42"})["success"] is False
    refused = _bounded(lambda: rig.plugin.cmd_apply_params({"params": {"exposure_time": 888.0}, "token": "SECRET-42"}))
    assert refused["success"] is False

    assert any("apply_params fields=['exposure_time'] ok=True" in line for line in lines), lines
    assert any("apply_params fields=[] ok=False" in line for line in lines), lines
    text = "\n".join(lines)
    for secret in ("123456", "SECRET-42", "777", "888"):
        assert secret not in text, f"значение {secret} попало в журнал: {lines}"


def test_reset_stats_сдвигает_окно_fps_без_подмены_часов_после_сброса(make, monkeypatch):
    """Окно после сброса начинается со сброса: 1 кадр за миллисекунды — это сотни кадров/с, а не 1 кадр за 100 с."""
    rig = make()
    plugin = rig.plugin
    published: list[tuple[str, object]] = []
    publish = rig.ctx.publish_metric
    rig.ctx.publish_metric = lambda name, value: (published.append((name, value)), publish(name, value))[0]
    plugin._tick_t0 = time.monotonic() - 100.0  # окно давно открыто; сброс обязан начать новое

    assert plugin.cmd_reset_stats({}) == {"success": True}
    plugin._on_frame(_good_frame(1))
    monkeypatch.setattr(plugin_base, "_TICK_S", 1e9)  # окно не созрело: кадр посчитан без публикации окна
    assert len(plugin.produce()) == 1
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)  # окно созрело сразу, `_tick_t0` не трогаем
    mark = len(published)
    plugin.produce()

    fps = [value for name, value in published[mark:] if name == "fps"]
    assert fps and fps[-1] > 0.5, f"окно fps не сдвинуто сбросом: {published[mark:]}"


# ---------------------------------------------------------------------------------------------- #
# timeout_s: отказ и лишние ключи
# ---------------------------------------------------------------------------------------------- #


def test_take_device_отказ_валидации_той_же_формы_и_start_не_зовётся(make, monkeypatch):
    starts: list = []
    monkeypatch.setattr(DeviceSession, "start", lambda self, timeout: starts.append(timeout) or True)
    rig = make()

    result = _bounded(lambda: rig.plugin.cmd_take_device({"timeout_s": 3600}))

    assert result == {
        "status": "error",
        "device_state": "closed",
        "error": "timeout_s: Input should be less than or equal to 30",
    }
    assert starts == []
    assert rig.plugin._session is None, "сеанс создан вопреки отказу валидации"


def test_release_device_отказ_валидации_той_же_формы_и_stop_не_зовётся(make, monkeypatch):
    stops: list = []
    original = DeviceSession.stop
    monkeypatch.setattr(
        DeviceSession, "stop", lambda self, timeout: (stops.append(timeout), original(self, timeout))[1]
    )
    rig = make()
    assert _bounded(lambda: rig.plugin.cmd_take_device({}))["status"] == "ok"

    result = _bounded(lambda: rig.plugin.cmd_release_device({"timeout_s": 0}))

    assert result == {
        "status": "error",
        "device_state": "grabbing",
        "error": "timeout_s: Input should be greater than 0",
    }
    assert stops == []
    assert rig.plugin._session.state == "grabbing", "захват остановлен вопреки отказу валидации"


def test_take_device_лишние_ключи_data_игнорируются(make, monkeypatch):
    starts: list = []
    original = DeviceSession.start
    monkeypatch.setattr(
        DeviceSession, "start", lambda self, timeout: (starts.append(timeout), original(self, timeout))[1]
    )
    rig = make()

    result = _bounded(lambda: rig.plugin.cmd_take_device({"timeout_s": 0.5, "unknown": "SECRET-42"}))

    assert result["status"] == "ok"
    assert starts == [0.5]
