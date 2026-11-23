# -*- coding: utf-8 -*-
"""Проводка 2.4b: настоящие `RegistersManager` и `PluginOrchestrator._on_register_update` -> журнал фейк-порта.

Правка идёт ровно тем путём, каким её шлёт GUI: `register_update` -> `_on_register_update` в «системном» потоке ->
`RegistersManager.set_field_value` -> колбэк подписки плагина -> `session.apply` -> поток-владелец -> порт.
Фейками остаются только порт и менеджер воркеров процесса (`MockProcessServices`). Ожидаемые значения — литералы.
Ожидание эффекта — с дедлайном; «ничего не случилось» подтверждает сторожевая правка после (подписка жива).
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import make_port

pytestmark = pytest.mark.timeout(60)

REG = "camera_device"
CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}
_NOISE = frozenset({"get_frame", "describe_param"})


class _Rig:
    """Настоящий плагин + `RegistersManager` + `PluginOrchestrator` (обработчик `register_update`) + фейк порта."""

    def __init__(self, monkeypatch, port, cfg: dict | None = None) -> None:
        self.port = port
        cfg = {**CFG, **(cfg or {})}
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        self.services = MockProcessServices(name="cam_wire", config=cfg)
        self.wm = WorkerManager("test_cam_wire")
        self.services.worker_manager = self.wm
        self.rm = RegistersManager(registers={REG: CameraDeviceRegisters()})
        self.ctx = PluginContext(services=self.services, config=cfg, registers=self.rm, plugin_name=REG)
        self.orch = PluginOrchestrator(self.services)
        self.orch._registers_manager = self.rm
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def register_update(self, field: str, value) -> dict:
        """`register_update` как из системного потока процесса: отдельный поток, результат обработчика."""
        box: dict = {}

        def system_thread() -> None:
            box["result"] = self.orch._on_register_update({"data": {"register": REG, "field": field, "value": value}})

        thread = threading.Thread(target=system_thread, name="system_sim", daemon=True)
        thread.start()
        thread.join(10.0)
        assert not thread.is_alive(), "обработчик register_update не вернулся за 10 с"
        return box["result"]

    def take(self) -> dict:
        return self.plugin.cmd_take_device({})

    def journal(self, start: int = 0) -> list[tuple]:
        return [(name, args) for name, args, _ in self.port.calls[start:] if name not in _NOISE]

    def close(self) -> None:
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(port=None, **cfg) -> _Rig:
        rig = _Rig(monkeypatch, port if port is not None else make_port(frame_period_s=0.02), cfg)
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


def _wrote(rig: _Rig, start: int, value: float) -> bool:
    return ("set_param", ("ExposureTime", value)) in rig.journal(start)


def test_register_update_доходит_до_журнала_фейка(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    result = rig.register_update("exposure_time", 1200.0)

    assert result["success"] is True, result
    _wait(lambda: _wrote(rig, base, 1200.0), "set_param(ExposureTime, 1200.0) в журнале фейка")
    _wait(lambda: ("get_param", ("ExposureTime",)) in rig.journal(base), "обратное чтение узла")
    assert [name for name, _ in rig.journal(base)] == ["set_param", "get_param"], "лишние вызовы порта (stop_grabbing?)"


def test_неизвестная_policy_не_ломает_колбэк_и_следующая_правка_доходит(make, monkeypatch):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)
    with monkeypatch.context() as local:
        local.setattr(rig.plugin, "_apply_policy", lambda field: "bogus")
        result = rig.register_update("exposure_time", 1100.0)  # ValueError сеанса колбэк ловит сам
    assert result["success"] is True, result
    time.sleep(0.2)
    assert rig.journal(base) == [], "неизвестная policy дошла до порта"
    assert get_or_create_health_state(rig.services).snapshot()["errors"] == 1, "исключение не учтено как инцидент"

    rig.register_update("exposure_time", 1300.0)

    _wait(lambda: _wrote(rig, base, 1300.0), "следующая правка после отказа policy")


def test_повторный_configure_без_shutdown_не_двоит_set_param(make):
    rig = make()
    rig.plugin.configure(rig.ctx)  # второй configure того же плагина без shutdown
    # у `RegistersManager` нет публичного счёта подписчиков: `_field_observers` читаем напрямую (колбэк на поле — один)
    assert len(rig.rm._field_observers[(REG, "exposure_time")]) == 1, "подписки задвоились"
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    rig.register_update("exposure_time", 1250.0)

    _wait(lambda: _wrote(rig, base, 1250.0), "правка дошла")
    time.sleep(0.3)
    writes = [call for call in rig.journal(base) if call == ("set_param", ("ExposureTime", 1250.0))]
    assert len(writes) == 1, f"set_param вызван {len(writes)} раз(а): подписки задвоились"


def test_правка_до_take_device_ничего_не_ломает_и_входит_в_план_следующего_take(make):
    rig = make()

    result = rig.register_update("exposure_time", 1500.0)

    assert result["success"] is True, result
    assert rig.port.calls == [], "порт тронут до take_device"
    assert rig.take()["status"] == "ok"
    assert _wrote(rig, 0, 1500.0), rig.journal()


def test_правка_при_busy_и_closed_не_принимается_без_исключения(make):
    busy = make(make_port(busy_for_s=60.0))
    assert busy.take()["device_state"] == "busy"
    base = len(busy.port.calls)
    assert busy.register_update("exposure_time", 1400.0)["success"] is True
    time.sleep(0.2)
    assert ("set_param", ("ExposureTime", 1400.0)) not in busy.journal(base)

    closed = make()
    assert closed.take()["status"] == "ok"
    closed.plugin.cmd_release_device({})
    base = len(closed.port.calls)
    assert closed.register_update("exposure_time", 1450.0)["success"] is True
    time.sleep(0.2)
    assert closed.journal(base) == []
    assert get_or_create_health_state(closed.services).snapshot()["errors"] == 0, "отказ приёма не инцидент"


def test_после_shutdown_правка_не_доходит_даже_при_новом_захвате(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.plugin.shutdown(rig.ctx)
    rig.plugin.shutdown(rig.ctx)  # повторный shutdown — пустая операция
    assert rig.take()["status"] == "ok"  # сеанс снова идёт: если подписка жива, правка дошла бы до порта
    base = len(rig.port.calls)

    assert rig.register_update("exposure_time", 1350.0)["success"] is True

    time.sleep(0.4)
    assert rig.journal(base) == [], "подписка пережила shutdown"


def test_после_повторного_configure_и_shutdown_не_остаётся_подписок_первого_configure(make):
    """Колбэки первого `configure` не теряются: иначе после `shutdown` они бы пережили плагин (утечка подписок)."""
    rig = make()
    rig.plugin.configure(rig.ctx)
    rig.plugin.shutdown(rig.ctx)
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    assert rig.register_update("exposure_time", 1360.0)["success"] is True

    time.sleep(0.4)
    assert rig.journal(base) == [], "подписка первого configure пережила shutdown"


# --- Дополнение по ревью Opus 2.4 (раунд 1) ---

SELF_TRIGGER = {"trigger_managed": True, "trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 77}
SOFTWARE = {**SELF_TRIGGER, "trigger_source": "Software", "trigger_period_ms": 55}
NO_REGRAB = fake_port.ALL_CAPABILITIES - {"restart_regrab"}


def _index_of(port, start: int, name: str) -> int | None:
    for i in range(start, len(port.calls)):
        if port.calls[i][0] == name:
            return i
    return None


def _edit_and_settle(rig: _Rig, field: str, value) -> int:
    """Правка как из GUI и ожидание перезахвата до `start_grabbing`; возвращает индекс начала окна журнала."""
    base = len(rig.port.calls)
    ok, err = rig.rm.set_field_value(REG, field, value)
    assert ok, err
    _wait(lambda: _index_of(rig.port, base, "start_grabbing") is not None, "перезахват дошёл до start_grabbing")
    time.sleep(0.2)
    return base


def _sets(rig: _Rig, base: int) -> list[tuple]:
    return [args for name, args, _ in rig.port.calls[base:] if name == "set_param"]


def test_дерево_обновляется_после_живой_правки_без_вызовов_produce(make):
    store = TreeStore()

    class Router:
        def send_async(self, msg, priority="normal"):
            data = msg["data"]
            if msg["command"] == "state.merge":
                store.merge(data["path"], data["data"])
            elif msg["command"] == "state.delete":
                store.delete(data["path"])

    rig = make()
    rig.ctx.state_proxy = StateProxy("cam_wire", router=Router())
    tree = "processes.cam_wire.state.plugins.camera_device"
    assert rig.take()["status"] == "ok"
    # `on_state(grabbing)` может прийти уже после ответа `take_device`: ждём исходное значение register'а в дереве
    _wait(lambda: store.get(tree).get("params", {}).get("exposure_time") == 10000.0, "исходное значение в дереве")
    t0 = time.monotonic()

    ok, err = rig.rm.set_field_value(REG, "exposure_time", 900.0)  # produce() не зовётся вовсе

    assert ok, err
    _wait(lambda: store.get(tree)["params"]["exposure_time"] == 900.0, "дерево получило 900.0", timeout=0.5)
    assert time.monotonic() - t0 < 0.5


def test_перезахват_пишет_regrab_ms_секундами(make):
    rig = make(**SELF_TRIGGER)
    timings: list[tuple[str, float]] = []
    record = rig.ctx.record_timing
    rig.ctx.record_timing = lambda name, d, tags=None: (timings.append((name, d)), record(name, d, tags))[0]
    assert rig.take()["status"] == "ok"

    _edit_and_settle(rig, "trigger_period_ms", 60)

    regrab = [value for name, value in timings if name == "regrab_ms"]
    assert len(regrab) == 1, timings
    assert 0.0 < regrab[0] < 5.0, "замер в секундах"


def test_смена_родителя_без_restart_regrab_не_пишет_закрытый_узел_потомка(make):
    rig = make(make_port(frame_period_s=0.02, capabilities=NO_REGRAB), **SELF_TRIGGER)
    assert rig.take()["status"] == "ok"

    base = _edit_and_settle(rig, "trigger_source", "Software")

    session = rig.plugin._session
    assert session.param_errors == {}, session.param_errors
    assert ("TriggerSelfTriggerPeriod", 77) not in _sets(rig, base), "период записан в закрытый узел"
    assert session.params["trigger_source"] == "Software"
    assert get_or_create_health_state(rig.services).snapshot()["errors"] == 0


def test_обратная_смена_родителя_включает_потомка_и_пишет_его_значение(make):
    rig = make(make_port(frame_period_s=0.02, capabilities=NO_REGRAB), **SOFTWARE)
    assert rig.take()["status"] == "ok"
    assert "trigger_period_ms" not in rig.plugin._session.params, "при Software период не пишется"

    base = _edit_and_settle(rig, "trigger_source", "SelfTrigger")

    session = rig.plugin._session
    assert ("TriggerSelfTriggerPeriod", 55) in _sets(rig, base)
    assert session.params["trigger_period_ms"] == 55
    assert session.param_errors == {}, session.param_errors


def test_смена_родителя_с_restart_regrab_пишет_только_изменённое_без_ошибок(make):
    rig = make(**SELF_TRIGGER)
    assert rig.take()["status"] == "ok"

    base = _edit_and_settle(rig, "trigger_source", "Software")

    assert rig.plugin._session.param_errors == {}
    assert _sets(rig, base) == [("TriggerSource", "Software")]
    names = [name for name, _, _ in rig.port.calls[base:]]
    assert "open" not in names and "close" not in names, names


def test_правка_пропущенного_потомка_прибор_не_трогает(make):
    rig = make(**SOFTWARE)  # источник Software: период самотриггера не пишется
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    assert rig.register_update("trigger_period_ms", 60)["success"] is True
    time.sleep(0.3)
    assert rig.journal(base) == [], "пропущенный шаг вызвал перезахват или запись"
    rig.register_update("exposure_time", 1111.0)  # подписка жива

    _wait(lambda: _wrote(rig, base, 1111.0), "сторожевая правка дошла")
    assert "stop_grabbing" not in [name for name, _ in rig.journal(base)]


def test_повтор_того_же_значения_после_отказа_записи_пишет_один_раз_и_снимает_ошибку(make):
    # прибор читает на 5 больше записанного: 900.0 не подтверждается чтением (допуск 0.9)
    port = make_port(frame_period_s=0.02, read_offset={"ExposureTime": 5.0})
    rig = make(port)
    assert rig.take()["status"] == "ok"
    base = len(port.calls)
    rig.register_update("exposure_time", 900.0)
    _wait(lambda: "exposure_time" in rig.plugin._session.param_errors, "отказ подтверждения записан")
    assert rig.plugin._session.param_errors["exposure_time"] == "не подтвердилось чтением"
    port._read_offset.clear()  # сбой снят
    base = len(port.calls)

    rig.register_update("exposure_time", 900.0)  # то же значение, но поле в `param_errors`

    _wait(lambda: "exposure_time" not in rig.plugin._session.param_errors, "ошибка снята повторной записью")
    time.sleep(0.2)
    writes = [call for call in rig.journal(base) if call == ("set_param", ("ExposureTime", 900.0))]
    assert len(writes) == 1, rig.journal(base)
    assert rig.plugin._session.params["exposure_time"] == 900.0


def test_повтор_того_же_значения_без_отказа_не_пишет_и_не_перезахватывает(make):
    rig = make(**SELF_TRIGGER)
    assert rig.take()["status"] == "ok"
    base = _edit_and_settle(rig, "trigger_period_ms", 60)  # restart: один перезахват
    assert rig.plugin._session.param_errors == {}
    base = len(rig.port.calls)

    rig.register_update("trigger_period_ms", 60)
    rig.register_update("exposure_time", 900.0)
    _wait(lambda: _wrote(rig, base, 900.0), "первая запись 900.0")
    mark = len(rig.port.calls)
    rig.register_update("exposure_time", 900.0)  # повтор без отказа
    time.sleep(0.4)

    assert rig.journal(mark) == [], "повтор того же значения дошёл до порта"
    assert "stop_grabbing" not in [name for name, _ in rig.journal(base)], "лишний перезахват"
