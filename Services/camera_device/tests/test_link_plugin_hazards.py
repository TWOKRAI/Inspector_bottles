# -*- coding: utf-8 -*-
"""Тесты опасности плагина камеры при переподключении (W2-a1): заглушка без `reconnecting`, ответ `take_device`,
строка личности после переподключения.

Автор — исполнитель (teamlead). Порт — фейк ядра, сеанс, `WorkerManager` и контекст плагина — настоящие.
Вызов, который может зависнуть, идёт в daemon-потоке с дедлайном `join`. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import PluginLevels
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port

_CFG = {
    "auto_start": False,
    "camera_id": 5,
    "device_select": "serial",
    "device_serial": "FAKE-0001",
    "timeout_ms": 100,
    "link_silence_s": 0.5,
    "reconnect_interval_s": 0.5,
}
_OPENED = "CameraDevicePlugin: device opened "


def _call(fn: Callable[[], Any], deadline: float = 8.0) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается тесту
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _await(pred: Callable[[], bool], message: str, deadline: float = 6.0) -> None:
    end = time.monotonic() + deadline
    while not pred():
        if time.monotonic() >= end:
            pytest.fail(f"не дождались за {deadline} с: {message}")
        time.sleep(0.01)


class _TreeRouter:
    """Приёмник настоящего `StateProxy`: `merge`/`delete` в настоящее дерево."""

    def __init__(self, store: TreeStore) -> None:
        self.store = store

    def send_async(self, msg: dict, priority: str = "normal") -> None:
        data = msg["data"]
        if msg["command"] == "state.merge":
            self.store.merge(data["path"], data["data"])
        elif msg["command"] == "state.delete":
            self.store.delete(data["path"])


class _Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, port: Any, **cfg: Any) -> None:
        config = {**_CFG, **cfg}
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        self.services = MockProcessServices(name="cam_link_hz", config=config, plugin_levels=PluginLevels())
        self.wm = WorkerManager("test_link_plugin_hazards")
        self.services.worker_manager = self.wm
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.tree = TreeStore()
        self.ctx.state_proxy = StateProxy("cam_link_hz", router=_TreeRouter(self.tree))
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def node(self) -> dict:
        """Узел плагина в настоящем дереве состояния (что видят оператор и MCP)."""
        return dict(self.tree.get("processes.cam_link_hz.state.plugins.camera_device", None) or {})

    def link(self) -> dict:
        """Блок `link` в настоящем дереве состояния."""
        return dict(self.node().get("link") or {})

    def take(self, **data: Any) -> dict:
        return _call(lambda: self.plugin.cmd_take_device(data))

    def release(self, **data: Any) -> dict:
        return _call(lambda: self.plugin.cmd_release_device(data))

    def lines(self, level: str, prefix: str) -> list[str]:
        return [e["msg"] for e in list(self.services.logs) if e["level"] == level and e["msg"].startswith(prefix)]

    def close(self) -> None:
        try:
            if getattr(self.plugin, "_session", None) is not None:
                _call(lambda: self.plugin.shutdown(self.ctx), 10.0)
        finally:
            self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(port: Any, **cfg: Any) -> _Rig:
        built = _Rig(monkeypatch, port, **cfg)
        rigs.append(built)
        return built

    yield factory
    for built in rigs:
        built.close()


class _BusyStub:
    """Сеанс-заглушка прежнего вида: только `state`, атрибута `reconnecting` нет."""

    state = "busy"


def test_readiness_without_reconnecting_attribute(make):
    """Заглушка без `reconnecting` в `busy`: прежний литерал причины, исключения нет."""
    rig = make(fake_port.make_port(frame_period_s=0.01))
    rig.plugin._session = _BusyStub()
    try:
        assert rig.plugin.readiness(rig.ctx) == [{"severity": "failure", "reason": "камера занята"}]
    finally:
        rig.plugin._session = None


@pytest.mark.parametrize(("reconnect", "expected"), [(True, True), (False, False)])
def test_take_reply_carries_reconnecting(make, reconnect, expected):
    """Прибор занят: ответ `take_device` несёт `reconnecting` (с `reconnect` — `True`, сеанс повторяет сам)."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=reconnect)
    reply = _call(lambda: rig.plugin.cmd_take_device({}))

    assert reply["status"] == "error"
    assert reply["device_state"] == "busy"
    assert reply["reconnecting"] is expected
    if reconnect:
        assert rig.plugin.readiness(rig.ctx) == [{"severity": "failure", "reason": "камера занята, переподключение"}]


def test_link_block_advances_while_lost_without_produce(make):
    """Стенд 2026-11-25: при `run fault` `produce()` не зовётся. Блок `link` в дереве всё равно идёт за сеансом:
    `attempts` и `lost_for_s` растут, пока связи нет; после возврата — `up`, `lost_for_s None`, дальше не растёт.
    """
    port = fake_port.make_port(frame_period_s=0.01)
    rig = make(port, reconnect=True)  # план по умолчанию: режима триггера нет, тишину решает проба
    assert _call(lambda: rig.plugin.cmd_take_device({}))["status"] == "ok"
    _await(lambda: rig.link().get("state") == "up", "link up после take_device")

    port.disconnect()  # дальше ни одного produce(): источник стоит (пауза или закрытый гейт работы)
    _await(lambda: rig.link().get("state") == "lost", "link lost в дереве")
    time.sleep(3.0)  # пауза попыток 0,5 с: за 3 с — около пяти повторов

    lost = rig.link()
    assert lost["reconnecting"] is True
    assert lost["attempts"] >= 2, lost
    assert 2 <= lost["lost_for_s"] <= 5, lost

    port.restore()
    _await(lambda: rig.link().get("state") == "up", "link up в дереве после возврата")
    up = rig.link()
    assert up["reconnecting"] is False
    assert up["lost_for_s"] is None
    assert up["outages"] == 1
    assert 2.0 <= up["last_outage_s"] <= 8.0, up
    time.sleep(1.5)
    assert rig.link() == up, "после возврата блок link не должен меняться"


def test_reconnect_does_not_repeat_identity_line(make):
    """Переподключение к тому же прибору: строка "device opened" не повторяется, вместо неё одна DEBUG."""
    port = fake_port.make_link_event_port(frame_period_s=0.01)
    rig = make(port, reconnect=True)
    assert _call(lambda: rig.plugin.cmd_take_device({}))["status"] == "ok"
    session = rig.plugin._session
    assert len(rig.lines("INFO", _OPENED)) == 1

    port.emit_link_event("disconnected")
    _await(lambda: session.link()["outages"] == 1, "потеря связи учтена")
    _await(lambda: session.state == "grabbing", "возврат в grabbing после переподключения")
    time.sleep(0.2)

    assert len(rig.lines("INFO", _OPENED)) == 1
    assert len(rig.lines("DEBUG", "CameraDevicePlugin: device reopened ")) == 1


# ---------------------------------------------------------------------------------------------- #
# Ревью стадии 5 (находки 2, 4, 5, 7a, 7b); `produce()` не зовётся нигде: источник стоит
# ---------------------------------------------------------------------------------------------- #


def test_release_from_failed_state_clears_tree_without_produce(make):
    """Находка 2: `release_device` из `busy` при переподключении — дерево сбрасывает `device_held` и `reconnecting`."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=True)
    assert rig.take()["status"] == "error"
    _await(lambda: rig.link().get("reconnecting") is True, "дерево: reconnecting True")

    assert rig.release()["status"] == "ok"
    _await(
        lambda: rig.node().get("device_held") is False and rig.link().get("reconnecting") is False,
        "дерево: device_held False и reconnecting False после release",
        3.0,
    )


def test_second_take_on_busy_camera_publishes_reconnecting(make):
    """Находка 4: take/release/take на занятом приборе — дерево снова показывает `reconnecting True` без окна 30 с."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=True, reconnect_interval_s=30.0)
    assert rig.take()["status"] == "error"
    _await(lambda: rig.link().get("reconnecting") is True, "дерево: reconnecting True после первого take", 3.0)
    assert rig.release()["status"] == "ok"

    assert rig.take()["status"] == "error"
    _await(lambda: rig.link().get("reconnecting") is True, "дерево: reconnecting True после второго take", 3.0)


def test_take_after_timed_out_release_is_not_reconnecting(make):
    """Находка 5: release истёк, пока повтор висит в `open`; следующий take не обещает переподключения."""
    port = fake_port.make_link_event_port(frame_period_s=0.01, open_delay_s=1.5)
    rig = make(port, reconnect=True)
    assert rig.take()["status"] == "ok"
    entered = threading.Event()
    original_open = port.open

    def watched_open(ident: Any) -> None:
        entered.set()
        original_open(ident)

    port.open = watched_open
    port.emit_link_event("disconnected")
    assert entered.wait(5.0), "повтор open не начался"

    assert rig.release(timeout_s=0.2)["status"] == "error"  # владелец ещё в open
    reply = rig.take()
    assert reply["status"] == "error"
    assert reply["device_state"] == "stopping"
    assert reply["reconnecting"] is False


def test_list_devices_answers_while_reconnecting(make):
    """Находка 7a: во время переподключения `list_devices` отвечает перечислением, а не «сеанс не в захвате»."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=True)
    assert rig.take()["status"] == "error"
    assert rig.plugin._session.reconnecting is True

    reply = _call(lambda: rig.plugin.cmd_list_devices({}))
    assert reply == {"success": True, "devices": [{"kind": "serial", "value": "FAKE-0001", "name": ""}]}


def test_take_with_new_identity_restarts_reconnect_cycle(make):
    """Находка 7b: повторный take с другой личностью при переподключении — новый цикл с новой личностью."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=True)
    first = rig.take()
    assert first["device_state"] == "busy" and first["reconnecting"] is True

    rig.plugin._reg.device_serial = "OTHER-0009"  # такого прибора в перечислении фейка нет
    second = rig.take()
    assert second["status"] == "error"
    assert second["device_state"] == "not_found"


# ---------------------------------------------------------------------------------------------- #
# Ревью стадии 5, раунд 2 (находки 2, 3, 4, 5)
# ---------------------------------------------------------------------------------------------- #

_NOT_GRABBING = {"success": False, "error": "сеанс не в захвате"}


def _errors(rig: _Rig) -> int:
    return sum(1 for e in list(rig.services.logs) if e["level"] == "ERROR")


def test_describe_params_refused_while_reconnecting(make):
    """Раунд 2, находка 2: при переподключении `describe_params` — прежний отказ, не `success` с `null`."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=True)
    assert rig.take()["status"] == "error"

    assert _call(lambda: rig.plugin.cmd_describe_params({})) == _NOT_GRABBING


def test_trigger_software_refused_quietly_while_reconnecting(make):
    """Раунд 2, находка 4: `trigger_software` при переподключении — тихий отказ, ни одной новой ERROR."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=True)
    assert rig.take()["status"] == "error"
    before = _errors(rig)

    replies = [_call(lambda: rig.plugin.cmd_trigger_software({})) for _ in range(3)]
    time.sleep(1.2)  # две паузы между попытками: команда, попавшая в ящик, уже исполнилась бы

    assert replies == [_NOT_GRABBING] * 3
    assert _errors(rig) == before


def test_take_with_new_identity_when_stop_times_out_refuses_explicitly(make):
    """Раунд 2, находка 3: новая личность, а `stop()` прежнего цикла истёк — явный отказ, лога перезапуска нет."""
    port = fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01, open_delay_s=2.0)
    rig = make(port, reconnect=True)
    assert rig.take()["status"] == "error"
    entered = threading.Event()
    original_open = port.open

    def watched_open(ident: Any) -> None:
        entered.set()
        original_open(ident)

    port.open = watched_open
    assert entered.wait(5.0), "повтор open не начался"
    rig.plugin._reg.device_serial = "OTHER-0009"

    reply = rig.take(timeout_s=0.2)  # владелец ещё ~2 с в open повтора

    assert reply["status"] == "error"
    assert reply["error"] == "прежний цикл ещё останавливается, повторите take_device"
    assert rig.lines("INFO", "CameraDevicePlugin: take_device: личность прибора сменилась, цикл перезапускается") == []


def test_slow_call_before_drain_keeps_newest_edit(make):
    """Раунд 2, находка 5: медленный `list_devices` в ящике перед `_drain` повтора и правка в это время —
    в приборе остаётся НОВОЕ значение, а не значение снимка плана."""
    from Services.camera_device.params import Step
    from Services.camera_device.testing.fake_port import FAKE_BINDINGS

    port = fake_port.make_link_event_port(frame_period_s=0.01)
    rig = make(port, reconnect=True, trigger_managed=True, trigger_mode="Off")  # свободный поток: ждёт кадр
    assert rig.take()["status"] == "ok"
    session = rig.plugin._session
    original_start = port.start_grabbing
    original_enum = port.sdk.enum_devices
    slow = {"armed": False}
    enum_entered = threading.Event()
    replies: list[dict] = []

    def slow_enum() -> Any:
        if slow["armed"]:
            slow["armed"] = False
            enum_entered.set()
            time.sleep(0.6)
        return original_enum()

    def start_with_queued_work() -> None:
        if not slow["armed"] and not enum_entered.is_set() and not replies:
            slow["armed"] = True
            worker = threading.Thread(target=lambda: replies.append(rig.plugin.cmd_list_devices({})), daemon=True)
            worker.start()
            time.sleep(0.1)  # `list_devices` уже в ящике
            session.apply([Step("exposure_time", FAKE_BINDINGS["exposure_time"], 5555.0)], "restart")
        original_start()

    port.sdk.enum_devices = slow_enum
    port.start_grabbing = start_with_queued_work
    port.emit_link_event("disconnected")
    assert enum_entered.wait(6.0), "медленный list_devices не начался"
    session.apply([Step("exposure_time", FAKE_BINDINGS["exposure_time"], 7777.0)], "restart")

    _await(lambda: session.state == "grabbing", "возврат в grabbing")
    time.sleep(0.5)
    writes = [a[1] for n, a, _t in list(port.calls) if n == "set_param" and a[0] == "ExposureTime"]
    assert writes[-1] == 7777.0, writes
