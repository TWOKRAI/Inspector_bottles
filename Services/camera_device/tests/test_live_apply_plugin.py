# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 2.4b: подписка плагина камеры на `RegistersManager` и политика `FieldMeta.apply`.

Написаны ДО кода по блокам DESIGN и ACCEPTANCE `plans/2026-10-18_camera-device-service/tasks/2.4b.md`
и по готовым `plugin_base.py`, `registers_base.py`, `session.py`, `params.py`, `testing/fake_port.py`.
Порт сеанса для веток restart/live ведёт `session.apply` (2.4a, в этом дереве его нет), поэтому проверяется
только НАБЛЮДАЕМЫЙ эффект: журнал фейк-порта `port.calls` и `session.params`/`param_errors`.
Правка идёт через настоящий `RegistersManager.set_field_value` (так до колбэка доходит `register_update`).
Ожидаемые значения — литералы из ACCEPTANCE. Вызов, который может заблокироваться, идёт в daemon-потоке
с дедлайном. «Ничего не делать» проверяется сторожевой правкой после: она доказывает, что подписка жива,
а пустой журнал — не следствие отсутствия подписки.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import Binding
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import FAKE_BINDINGS, make_port

pytestmark = pytest.mark.timeout(60)

PROCESS_NAME = "cam_live"
REG = "camera_device"
FAKE_CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}
TRIGGER_CFG = {**FAKE_CFG, "trigger_managed": True, "trigger_mode": "On", "trigger_source": "SelfTrigger"}
# Шумовые записи журнала: кадры идут всё время захвата, `describe_param` — разовый кэш шага узла.
_NOISE = frozenset({"get_frame", "describe_param"})
DEADLINE_S = 5.0  # срок появления эффекта правки; машина общая, поэтому с большим запасом
SETTLE_S = 0.2  # выдержка перед проверкой «ничего не случилось»


class _BoundConfigPlugin(CameraDevicePlugin):
    """База с лишней привязкой: поле `camera_id` (apply не задан) привязано к узлу ExposureTime.

    Нужна, чтобы проверить политику «apply = None -> прибор не трогается» на поле, у которого шаг в плане ЕСТЬ.
    """

    def bindings(self) -> dict[str, Binding]:
        return {**FAKE_BINDINGS, "camera_id": Binding("genicam", "ExposureTime", "float")}


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


class _Rig:
    """Настоящий плагин + настоящий `RegistersManager` (или без него) + фейк порта."""

    def __init__(self, monkeypatch, cfg: dict, port, *, with_registers: bool = True, plugin_cls=CameraDevicePlugin):
        self.port = port
        self.warnings: list[str] = []
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        services = MockProcessServices(name=PROCESS_NAME, config=cfg)
        services.log_warning = lambda msg, **kwargs: self.warnings.append(msg)
        self.wm = WorkerManager("test_cam_live")
        services.worker_manager = self.wm
        self.rm = RegistersManager(registers={REG: CameraDeviceRegisters()}) if with_registers else None
        self.ctx = PluginContext(services=services, config=cfg, registers=self.rm, plugin_name=REG)
        self.plugin = plugin_cls()

    def configure(self) -> _Rig:
        _bounded(lambda: self.plugin.configure(self.ctx))
        return self

    def take(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_take_device({}))

    def edit(self, field: str, value):
        """Правка поля как из GUI: настоящий `set_field_value` (колбэки подписчиков — в этом потоке)."""
        return _bounded(lambda: self.rm.set_field_value(REG, field, value))

    def taken(self) -> _Rig:
        """configure + take_device: захват идёт, ответ `ok`."""
        self.configure()
        result = self.take()
        assert result["status"] == "ok" and result["device_state"] == "grabbing", result
        return self

    def close(self) -> None:
        if hasattr(self.plugin, "_session"):  # configure не дошёл до конца — освобождать нечего
            self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(cfg: dict, *, port=None, **kwargs) -> _Rig:
        item = _Rig(monkeypatch, cfg, port if port is not None else make_port(frame_period_s=0.02), **kwargs)
        built.append(item)
        return item

    yield factory
    for item in built:
        item.close()


def _journal(port, start: int) -> list[tuple]:
    """Записи журнала с индекса `start` как `(имя, args)`, без кадров и `describe_param`."""
    return [(name, args) for name, args, _ in port.calls[start:] if name not in _NOISE]


def _wait(predicate, what: str, timeout: float = DEADLINE_S) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(f"за {timeout} с не случилось: {what}")


def _index_of(port, start: int, name: str, args: tuple | None = None) -> int | None:
    """Индекс первой записи `name` (и `args`, если заданы) в журнале с `start`; `None` — нет."""
    for i in range(start, len(port.calls)):
        call = port.calls[i]
        if call[0] == name and (args is None or call[1] == args):
            return i
    return None


# ---------------------------------------------------------------------------------------------- #
# ACCEPTANCE 1: live
# ---------------------------------------------------------------------------------------------- #


def test_exposure_live_пишется_без_остановки_захвата(make):
    """Строка 1: `exposure_time=1200.0` при захвате (apply live) -> `set_param, get_param`, `stop_grabbing` нет."""
    r = make(FAKE_CFG).taken()
    base = len(r.port.calls)

    ok, err = r.edit("exposure_time", 1200.0)

    assert ok, err
    _wait(lambda: _index_of(r.port, base, "get_param", ("ExposureTime",)) is not None, "правка дошла до порта")
    time.sleep(SETTLE_S)
    assert _journal(r.port, base) == [
        ("set_param", ("ExposureTime", 1200.0)),
        ("get_param", ("ExposureTime",)),
    ]


# ---------------------------------------------------------------------------------------------- #
# ACCEPTANCE 2: restart
# ---------------------------------------------------------------------------------------------- #


def test_trigger_period_restart_пишется_между_stop_и_start_grabbing(make):
    """Строка 2: trigger_managed=true; `trigger_period_ms=60` (apply restart, фейк restart_regrab) ->
    между `stop_grabbing` и следующим `start_grabbing` ровно `set_param, get_param`; `open`/`close` нет;
    `params["trigger_period_ms"] == 60`, `param_errors` без поля."""
    r = make(TRIGGER_CFG).taken()
    base = len(r.port.calls)

    ok, err = r.edit("trigger_period_ms", 60)

    assert ok, err
    _wait(lambda: _index_of(r.port, base, "start_grabbing") is not None, "перезахват дошёл до start_grabbing")
    stop_at = _index_of(r.port, base, "stop_grabbing")
    assert stop_at is not None, "перед записью узла нет stop_grabbing (restart пишется как live?)"
    start_at = _index_of(r.port, stop_at, "start_grabbing")
    assert start_at is not None
    between = [(n, a) for n, a, _ in r.port.calls[stop_at + 1 : start_at] if n not in _NOISE]
    assert between == [
        ("set_param", ("TriggerSelfTriggerPeriod", 60)),
        ("get_param", ("TriggerSelfTriggerPeriod",)),
    ]
    window = [name for name, _ in _journal(r.port, base)]
    assert "open" not in window and "close" not in window, window
    session = r.plugin._session
    assert session.params["trigger_period_ms"] == 60
    assert "trigger_period_ms" not in session.param_errors


# ---------------------------------------------------------------------------------------------- #
# ACCEPTANCE 3 + 4: «ничего не делать»
# ---------------------------------------------------------------------------------------------- #

# (метка, действие над rig, значение сторожевой правки exposure_time). Каждое действие — со своей сторожевой
# правкой: журнал между действиями обязан содержать ТОЛЬКО её запись и чтение.
_NOOP_ACTIONS = [
    ("trigger_period_ms=60 при trigger_managed=false", lambda r: r.edit("trigger_period_ms", 60), 1001.0),
    ("config-поле device_serial", lambda r: r.edit("device_serial", "SN-OTHER"), 1002.0),
    ("неизвестное поле", lambda r: r.edit("no_such_field", 1), 1003.0),
    ("привязанное поле camera_id с apply=None", lambda r: r.edit("camera_id", 7), 1004.0),
    ("прямая запись plugin._reg.exposure_time", lambda r: setattr(r.plugin._reg, "exposure_time", 900.0), 1005.0),
]


def test_без_политики_прибор_не_трогается_и_исключений_нет(make):
    """Строки 3 и 4: умолчание (`trigger_managed: false`) + `trigger_period_ms=60`; поле с apply `config`
    (`device_serial`); неизвестное поле; привязанное поле без apply; прямая запись `_reg.exposure_time` ->
    ни одного `stop_grabbing`/`set_param` от самого действия, исключения нет. Подписка при этом жива:
    следующая сторожевая правка exposure_time доходит до порта."""
    r = make(FAKE_CFG, plugin_cls=_BoundConfigPlugin).taken()
    for label, action, sentinel in _NOOP_ACTIONS:
        base = len(r.port.calls)

        action(r)  # исключение здесь — провал теста
        ok, err = r.edit("exposure_time", sentinel)

        assert ok, err
        _wait(
            lambda: _index_of(r.port, base, "get_param", ("ExposureTime",)) is not None,
            f"сторожевая правка {sentinel} дошла до порта (подписки нет?) после: {label}",
        )
        time.sleep(0.1)
        assert _journal(r.port, base) == [
            ("set_param", ("ExposureTime", sentinel)),
            ("get_param", ("ExposureTime",)),
        ], f"прибор тронут действием: {label}"


# ---------------------------------------------------------------------------------------------- #
# ACCEPTANCE 5: ctx.registers is None
# ---------------------------------------------------------------------------------------------- #


def test_без_registers_configure_не_бросает_один_WARNING_и_take_работает(make):
    """Строка 5: `ctx.registers is None` -> `configure` не бросает, WARNING ровно один; `take_device` как раньше."""
    r = make(FAKE_CFG, with_registers=False)

    r.configure()  # исключение — провал

    assert len(r.warnings) == 1, r.warnings
    result = r.take()
    assert result["status"] == "ok"
    assert result["device_state"] == "grabbing"


# ---------------------------------------------------------------------------------------------- #
# ACCEPTANCE 6: потоки и неблокирующий produce
# ---------------------------------------------------------------------------------------------- #


def test_колбэк_не_зовёт_порт_и_produce_не_блокируется_при_перезахвате(make, monkeypatch):
    """Строка 6: фейк без `restart_regrab`, `open_delay_s=0.3`; правка `trigger_period_ms=60` -> перезахват
    (close/open 0.3 с/запись/start_grabbing) идёт не в потоке колбэка; сам колбэк возвращается быстро;
    `produce()` в daemon-потоке во время перезахвата не блокируется (порог 0.15 с при блокировке >= 0.3 с)."""
    monkeypatch.setattr(plugin_base, "_TICK_S", 0.02)  # `produce` часто ходит в `_sync_events` (замки сеанса)
    port = make_port(
        frame_period_s=0.02, open_delay_s=0.3, capabilities=fake_port.ALL_CAPABILITIES - {"restart_regrab"}
    )
    r = make(TRIGGER_CFG, port=port).taken()
    base = len(port.calls)

    durations: list[float] = []
    producer_ident: list[int] = []
    stop = threading.Event()

    def producer() -> None:
        producer_ident.append(threading.get_ident())
        while not stop.is_set():
            t0 = time.perf_counter()
            r.plugin.produce()
            durations.append(time.perf_counter() - t0)
            time.sleep(0.005)

    editor_ident: list[int] = []
    edit_result: dict = {}
    edited = threading.Event()
    release = threading.Event()

    def editor() -> None:  # поток живёт до конца теста: идентификатор не переиспользуется
        editor_ident.append(threading.get_ident())
        t0 = time.perf_counter()
        edit_result["res"] = r.rm.set_field_value(REG, "trigger_period_ms", 60)
        edit_result["s"] = time.perf_counter() - t0
        edited.set()
        release.wait(30)

    threads = [threading.Thread(target=producer, daemon=True), threading.Thread(target=editor, daemon=True)]
    try:
        threads[0].start()
        threads[1].start()
        assert edited.wait(DEADLINE_S), "set_field_value не вернулся: колбэк блокирует вызывающего"
        _wait(lambda: _index_of(port, base, "start_grabbing") is not None, "перезахват дошёл до start_grabbing")
        time.sleep(SETTLE_S)
        stop.set()
        threads[0].join(2.0)
        assert edit_result["res"][0] is True, edit_result["res"]
        assert edit_result["s"] < 0.15, f"колбэк вернулся за {edit_result['s']:.3f} с"
        assert len(durations) >= 5, "produce почти не вызывался за окно перезахвата"
        assert max(durations) < 0.15, f"produce блокировался на {max(durations):.3f} с"
        assert _index_of(port, base, "open") is not None, "перезахвата (open) не было: проверка пуста"
        foreign = {editor_ident[0], producer_ident[0], threading.get_ident()}
        offenders = [(n, a) for n, a, ident in port.calls[base:] if ident in foreign]
        assert offenders == [], f"порт зовётся из потока колбэка/produce/теста: {offenders}"
    finally:
        stop.set()
        release.set()
        for thread in threads:
            thread.join(2.0)


# ---------------------------------------------------------------------------------------------- #
# ACCEPTANCE 7: shutdown снимает подписки
# ---------------------------------------------------------------------------------------------- #


def test_shutdown_снимает_подписки_и_повторный_configure_не_двоит_запись(make):
    """Строка 7: после `shutdown` правка не доходит до порта; `configure` + `shutdown` + `configure` + правка
    дают ровно один `set_param(ExposureTime, 1200.0)` (повторный configure без unsubscribe удваивает колбэки)."""
    after = make(FAKE_CFG).taken()
    _bounded(lambda: after.plugin.shutdown(after.ctx))
    base = len(after.port.calls)

    after.edit("exposure_time", 1200.0)
    time.sleep(0.5)

    assert _index_of(after.port, base, "set_param", ("ExposureTime", 1200.0)) is None, "правка дошла после shutdown"

    again = make(FAKE_CFG)
    again.configure()
    _bounded(lambda: again.plugin.shutdown(again.ctx))
    again.configure()
    result = again.take()
    assert result["status"] == "ok", result
    base = len(again.port.calls)

    ok, err = again.edit("exposure_time", 1200.0)

    assert ok, err
    _wait(lambda: _index_of(again.port, base, "set_param", ("ExposureTime", 1200.0)) is not None, "правка дошла")
    time.sleep(0.3)
    writes = [
        call for call in again.port.calls[base:] if call[0] == "set_param" and call[1] == ("ExposureTime", 1200.0)
    ]
    assert len(writes) == 1, f"set_param вызван {len(writes)} раз(а): подписки задвоились"
