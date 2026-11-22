# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 2.3a: общий register, идентичность прибора, план run/rest, конверт item.

Написаны ДО кода по блокам ACCEPTANCE и DESIGN `plans/2026-10-18_camera-device-service/tasks/2.3a.md`
и по готовым интерфейсам (`interface.py`, `params.py`, `profiles.py`, `testing/fake_port.py`).
Проверяется наблюдаемое: журнал фейка `port.calls`, ответы `take_device`/`release_device`, `register`,
item из `produce()`, строки `ctx.log_warning`. Ожидаемые значения — литералы из ACCEPTANCE.

Настоящий плагин собирается как в `test_slice_plugin.py`: `PluginContext` над `MockProcessServices`,
настоящий `WorkerManager`. Вызов, который может заблокироваться, идёт в daemon-потоке с дедлайном.
Пункты, зависящие от ещё не существующих сущностей (`FAKE_BINDINGS`, поля register'а, хуки базы,
`set_profiles`), красные до кода; `test_item_...` и `test_потоки_...` — регрессионная защита (зелёные до кода).
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import Binding, DeviceIdentity, RawFrame
from Services.camera_device.params import check_bindings
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import make_port

PROCESS_NAME = "cam_fake"
REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_CFG = {"auto_start": False, "camera_id": 3}
FAKE_CFG = {**BASE_CFG, "device_select": "serial", "device_serial": "FAKE-0001"}
ITEM_KEYS = {
    "frame",
    "camera_id",
    "device_id",
    "seq_id",
    "frame_id",
    "timestamp",
    "ts",
    "pixel_format",
    "width",
    "height",
    "device_frame_num",
}


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


class _Built:
    """Настоящий плагин над фейковым портом; строки WARNING собираются в `warnings`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, cfg: dict, port, plugin_cls, patch_create: bool) -> None:
        self.port = port
        self.warnings: list[str] = []
        if patch_create:
            monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        services = MockProcessServices(name=PROCESS_NAME, config=cfg)
        # ctx.log_warning оборачивается в functools.partial(..., module=<имя плагина>): подмена принимает **kwargs
        services.log_warning = lambda msg, **kwargs: self.warnings.append(msg)
        self.wm = WorkerManager("test_cam")
        services.worker_manager = self.wm
        self.ctx = PluginContext(services=services, config=cfg, plugin_name=plugin_cls.name)
        self.plugin = plugin_cls()

    def configure(self) -> _Built:
        self.plugin.configure(self.ctx)
        return self

    def take(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_take_device({}))

    def release(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_release_device({}))

    def close(self) -> None:
        if hasattr(self.plugin, "_session"):  # configure не дошёл до конца — освобождать нечего
            self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Built] = []

    def factory(cfg: dict, *, port=None, plugin_cls=CameraDevicePlugin, patch_create: bool = True) -> _Built:
        item = _Built(
            monkeypatch, cfg, port if port is not None else make_port(frame_period_s=0.02), plugin_cls, patch_create
        )
        built.append(item)
        return item

    yield factory
    for item in built:
        item.close()


def _names(port) -> list[str]:
    return [call[0] for call in port.calls]


def _rw(calls) -> list[tuple]:
    """Записи и чтения узлов из куска журнала: `(имя, args)`; `describe_param` и прочее отброшены."""
    return [(name, args) for name, args, _ in calls if name in ("set_param", "get_param")]


def _run_window(port, nth_open: int = 0) -> list:
    """Журнал между `open` и следующим за ним `start_grabbing`."""
    names = _names(port)
    first = [i for i, name in enumerate(names) if name == "open"][nth_open]
    return port.calls[first + 1 : names.index("start_grabbing", first)]


def _rest_window(port) -> list:
    """Журнал после первого `stop_grabbing` (после `start_grabbing`)."""
    names = _names(port)
    return port.calls[names.index("stop_grabbing", names.index("start_grabbing")) + 1 :]


def _pairs(*writes: tuple[str, object]) -> list[tuple]:
    """Ожидаемый кусок журнала: за каждой записью узла идёт чтение этого узла."""
    out: list[tuple] = []
    for key, value in writes:
        out.append(("set_param", (key, value)))
        out.append(("get_param", (key,)))
    return out


# ---------------------------------------------------------------------------------------------- #
# Идентичность и WARNING (Р1, Р3)
# ---------------------------------------------------------------------------------------------- #

_SELECT = "device_select="


@pytest.mark.parametrize(
    ("cfg", "error_field", "canaries", "warn_prefix"),
    [
        pytest.param({}, "device_serial", (), None, id="умолчание_serial_с_пустым_серийником"),
        pytest.param(
            {"device_select": "serial", "device_serial": "", "device_ip": "10.77.0.5", "device_url": "rtsp://canary"},
            "device_serial",
            ("10.77.0.5", "rtsp://canary"),
            None,
            id="serial_пуст",
        ),
        pytest.param(
            {"device_select": "ip", "device_ip": "", "device_serial": "SN-CANARY-9"},
            "device_ip",
            ("SN-CANARY-9",),
            None,
            id="ip_пуст",
        ),
        pytest.param(
            {"device_select": "url", "device_url": "", "device_serial": "SN-CANARY-9"},
            "device_url",
            ("SN-CANARY-9",),
            None,
            id="url_пуст",
        ),
        pytest.param({"device_select": "first"}, None, (), "device_select=first", id="first_предупреждает"),
        pytest.param(
            {"device_select": "first", "device_serial": "FAKE-0001"},
            None,
            (),
            "device_select=first",
            id="first_предупреждает_всегда_даже_с_серийником",
        ),
        pytest.param(
            {"device_select": "index", "device_index": 0}, None, (), "device_select=index", id="index_без_имени"
        ),
        pytest.param(
            {"device_select": "index", "device_index": 0, "device_name": "Cam A"},
            None,
            (),
            None,
            id="index_с_именем_молчит",
        ),
        pytest.param(
            {"device_select": "serial", "device_serial": "FAKE-0001"}, None, (), None, id="serial_задан_молчит"
        ),
    ],
)
def test_идентичность_и_WARNING(make, cfg, error_field, canaries, warn_prefix):
    """Умолчание `serial`; пустое поле идентичности -> `ValueError` с именем поля и БЕЗ значений;
    `first` предупреждает всегда, `index` без имени предупреждает, остальное молчит."""
    built = make({**BASE_CFG, **cfg})
    if error_field is not None:
        with pytest.raises(ValueError) as exc_info:
            built.plugin.configure(built.ctx)
        text = str(exc_info.value)
        assert error_field in text
        for canary in canaries:
            assert canary not in text, f"значение {canary!r} попало в текст ошибки"
        return
    built.configure()
    select_warnings = [w for w in built.warnings if w.startswith(_SELECT)]
    if warn_prefix is None:
        assert select_warnings == []
    else:
        assert any(w.startswith(warn_prefix) for w in select_warnings), built.warnings


# ---------------------------------------------------------------------------------------------- #
# Сторож
# ---------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("watchdog_s", "must_raise"),
    [
        pytest.param(0.25, True, id="меньше_таймаута"),
        pytest.param(0.75, True, id="равен_таймауту"),
        pytest.param(0.751, False, id="чуть_больше_таймаута"),
    ],
)
def test_watchdog_не_больше_таймаута_кадра_отказ_в_configure(make, watchdog_s, must_raise):
    """`watchdog_s <= timeout_ms/1000` -> `ValueError` в `configure`, текст называет `watchdog_s` без значений;
    допустимый конфиг -> `take_device` не бросает и отвечает `ok`."""
    built = make({**FAKE_CFG, "timeout_ms": 750, "watchdog_s": watchdog_s})
    if must_raise:
        with pytest.raises(ValueError) as exc_info:
            built.plugin.configure(built.ctx)
        text = str(exc_info.value)
        assert "watchdog_s" in text
        assert str(watchdog_s) not in text
        assert "750" not in text
        return
    built.configure()
    assert built.take()["status"] == "ok"


# ---------------------------------------------------------------------------------------------- #
# Item (Р10): регрессионная защита, ожидаемо зелёный до кода
# ---------------------------------------------------------------------------------------------- #


def test_item_seq_id_растёт_по_кадрам_без_переполнения(make):
    """130 принятых кадров и один `produce()`: `seq_id == 130` (не 9 = 130 % 121), `frame_id == seq_id`, `ts` — wall."""
    built = make(FAKE_CFG).configure()
    plugin = built.plugin
    for number in range(1, 131):
        plugin._on_frame(RawFrame(bytearray(range(8)), 4, 2, "mono8", number))
    items = plugin.produce()
    assert len(items) == 1
    item = items[0]
    assert ITEM_KEYS <= set(item)
    assert item["seq_id"] == 130
    assert item["frame_id"] == 130
    assert item["camera_id"] == 3
    assert (item["width"], item["height"], item["pixel_format"], item["device_frame_num"]) == (4, 2, "mono8", 130)
    assert item["frame"].shape == (2, 4)
    assert isinstance(item["ts"], float)
    assert abs(item["ts"] - time.time()) < 1.0
    assert isinstance(item["timestamp"], float)
    assert 0 < item["timestamp"] <= time.monotonic()


# ---------------------------------------------------------------------------------------------- #
# Register и привязки фейка (Р4)
# ---------------------------------------------------------------------------------------------- #

_TRIGGER_GROUP = ("trigger_managed", "trigger_mode", "trigger_source", "trigger_period_ms")
_DEFAULTS = {
    "driver": "fake",
    "device_select": "serial",
    "timeout_ms": 500,
    "watchdog_s": 5.0,
    "trigger_managed": False,
    "trigger_mode": "Off",
    "trigger_source": "Line0",
    "trigger_period_ms": 40,
    "exposure_time": 10000.0,
    "rest_managed": False,
    "rest_trigger_mode": "On",
    "rest_trigger_source": "Line0",
}
_REQUIRED = {
    "driver",
    "camera_id",
    "device_select",
    "device_serial",
    "device_ip",
    "device_url",
    "device_index",
    "device_name",
    "auto_start",
    "timeout_ms",
    "watchdog_s",
    "frames",
    "device_state",
    "trigger_managed",
    "trigger_mode",
    "trigger_source",
    "trigger_period_ms",
    "exposure_time",
    "rest_managed",
    "rest_trigger_mode",
    "rest_trigger_source",
}


def test_register_поля_умолчания_и_таблица_привязки_фейка():
    """Состав и умолчания полей; `device_id`, `restart_backoff_s`, `param_errors` нет; порядок группы триггера;
    `FAKE_BINDINGS` согласована с register'ом (`check_bindings`, Р4) и ловит опечатку ключа."""
    fields = CameraDeviceRegisters.model_fields
    assert _REQUIRED <= set(fields)
    assert not {"device_id", "restart_backoff_s", "param_errors"} & set(fields)
    for name, expected in _DEFAULTS.items():
        assert fields[name].default == expected, name
    order = list(fields)
    assert [order.index(name) for name in (*_TRIGGER_GROUP, "exposure_time")] == sorted(
        order.index(name) for name in (*_TRIGGER_GROUP, "exposure_time")
    ), "группа триггера объявлена раньше exposure_time и в порядке managed, mode, source, period"
    meta = CameraDeviceRegisters.get_all_fields_meta()
    for name in _TRIGGER_GROUP[1:]:
        assert (meta[name].apply, meta[name].ui_group) == ("restart", "trigger"), name
    assert (meta["exposure_time"].apply, meta["timeout_ms"].min) == ("live", 1)

    expected_bindings = {
        "trigger_mode": Binding("genicam", "TriggerMode", "enum"),
        "trigger_source": Binding("genicam", "TriggerSource", "enum"),
        "trigger_period_ms": Binding("genicam", "TriggerSelfTriggerPeriod", "int"),
        "exposure_time": Binding("genicam", "ExposureTime", "float"),
    }
    assert fake_port.FAKE_BINDINGS == expected_bindings
    vendor_fields = set(fields) - {"trigger_mode", "trigger_source", "trigger_period_ms", "exposure_time"}
    check_bindings(CameraDeviceRegisters, fake_port.FAKE_BINDINGS, vendor_fields=vendor_fields)
    typo = {
        ("trigger_periodms" if key == "trigger_period_ms" else key): b for key, b in fake_port.FAKE_BINDINGS.items()
    }
    with pytest.raises(ValueError) as exc_info:
        check_bindings(CameraDeviceRegisters, typo, vendor_fields=vendor_fields)
    assert "trigger_periodms" in str(exc_info.value)


# ---------------------------------------------------------------------------------------------- #
# План run/rest из register'а (амендмент 4, Р6)
# ---------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("cfg", "run_rw", "params", "rest_rw"),
    [
        pytest.param({}, _pairs(("ExposureTime", 10000.0)), {"exposure_time": 10000.0}, [], id="run_без_триггера"),
        pytest.param(
            {"trigger_managed": True, "trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 40},
            _pairs(
                ("TriggerMode", "On"),
                ("TriggerSource", "SelfTrigger"),
                ("TriggerSelfTriggerPeriod", 40),
                ("ExposureTime", 10000.0),
            ),
            {"trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 40, "exposure_time": 10000.0},
            [],
            id="run_selftrigger",
        ),
        pytest.param(
            {"rest_managed": True, "rest_trigger_mode": "On", "rest_trigger_source": "Line0"},
            _pairs(("ExposureTime", 10000.0)),
            {"exposure_time": 10000.0},
            _pairs(("TriggerMode", "On"), ("TriggerSource", "Line0")),
            id="rest_после_release",
        ),
    ],
)
def test_план_run_и_rest_из_register(make, cfg, run_rw, params, rest_rw):
    """`take_device` пишет run между `open` и `start_grabbing` (триггер — только при `trigger_managed`);
    после `release_device` и `stop_grabbing` пишется rest (только при `rest_managed`)."""
    built = make({**FAKE_CFG, **cfg}).configure()
    assert built.take()["status"] == "ok"
    assert _rw(_run_window(built.port)) == run_rw
    assert built.plugin._session.params == params
    assert built.release()["status"] == "ok"
    assert _rw(_rest_window(built.port)) == rest_rw


def test_план_строится_при_каждом_старте(make):
    """`take`, `release`, `exposure_time = 900.0`, `take` -> второй цикл пишет ExposureTime 900.0, первый — 10000.0."""
    built = make(FAKE_CFG).configure()
    assert built.take()["status"] == "ok"
    assert built.release()["status"] == "ok"
    built.plugin._reg.exposure_time = 900.0
    assert built.take()["status"] == "ok"
    assert _rw(_run_window(built.port, 0)) == _pairs(("ExposureTime", 10000.0))
    assert _rw(_run_window(built.port, 1)) == _pairs(("ExposureTime", 900.0))


# ---------------------------------------------------------------------------------------------- #
# Идентичность доходит до сеанса (сквозная)
# ---------------------------------------------------------------------------------------------- #

_TWO_DEVICES = ("FAKE-0001", "FAKE-0002")


@pytest.mark.parametrize(
    ("cfg", "devices", "status", "state", "opened"),
    [
        pytest.param(
            {"device_select": "first", "device_serial": ""},
            _TWO_DEVICES,
            "ok",
            "grabbing",
            [("open", ("serial", "FAKE-0001"))],
            id="first_берёт_первый_из_двух",
        ),
        pytest.param(
            {"device_select": "serial", "device_serial": "NOPE"}, None, "error", "not_found", [], id="serial_NOPE"
        ),
        pytest.param(
            {"device_select": "serial", "device_serial": "FAKE-0001"},
            None,
            "ok",
            "grabbing",
            [("open", ("serial", "FAKE-0001"))],
            id="serial_FAKE",
        ),
    ],
)
def test_идентичность_доходит_до_сеанса(make, monkeypatch, cfg, devices, status, state, opened):
    """Что выбрано в register'е, то и открывается: чужой серийник -> `error` + `not_found` без `open`."""
    built = make({**BASE_CFG, **cfg})
    if devices is not None:
        found = [DeviceIdentity("serial", serial) for serial in devices]
        monkeypatch.setattr(built.port.sdk, "enum_devices", lambda: found)  # фейк отдаёт один прибор
    built.configure()
    assert built.take()["status"] == status
    assert built.plugin._session.state == state
    assert [call[:2] for call in built.port.calls if call[0] == "open"] == opened


# ---------------------------------------------------------------------------------------------- #
# Хуки базы: create_port() и bindings()
# ---------------------------------------------------------------------------------------------- #


def test_хуки_базы_create_port_и_bindings_подкласса(make, monkeypatch):
    """Подкласс открывает СВОЙ порт (модульная `create_port` не вызвана) и строит план по СВОИМ привязкам."""
    own = make_port(frame_period_s=0.02)
    other = make_port(frame_period_s=0.02)
    module_calls: list[str] = []

    def module_create_port(driver: str):
        module_calls.append(driver)
        return other

    class P(CameraDevicePlugin):
        def create_port(self):
            return own

        def bindings(self):
            return {"exposure_time": Binding("genicam", "ExposureTime", "float")}

    cfg = {**FAKE_CFG, "trigger_managed": True, "trigger_mode": "On"}
    built = make(cfg, port=other, plugin_cls=P, patch_create=False)
    monkeypatch.setattr(plugin_base, "create_port", module_create_port)
    built.configure()
    assert built.take()["status"] == "ok"
    assert "open" in _names(own)
    assert module_calls == []
    assert other.calls == []
    set_keys = [args[0] for name, args, _ in own.calls if name == "set_param"]
    assert "TriggerMode" not in set_keys
    assert "ExposureTime" in set_keys


# ---------------------------------------------------------------------------------------------- #
# Потоки: новых нет, ALLOWLIST G6 R1 не тронут
# ---------------------------------------------------------------------------------------------- #

_BASE_FILES = ("Services/camera_device/plugin_base.py", "Services/camera_device/registers_base.py")
_THREAD_PATTERN = r"threading\.Thread|KeyedExecutor|ThreadPoolExecutor"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=60, check=False)


def test_потоки_база_не_создаёт_потоков_и_allowlist_G6_не_тронут():
    """`git grep` по файлам базы пуст (код 1 = нет совпадений, не ошибка); `tables.py` G6 R1 без правок."""
    tracked = _git("ls-files", "--", *_BASE_FILES).stdout.split()
    assert sorted(tracked) == sorted(_BASE_FILES), "git grep по неотслеживаемому файлу пройдёт вхолостую"
    control = _git("grep", "-lE", "class CameraDevice", "--", *_BASE_FILES)
    assert control.returncode == 0 and sorted(control.stdout.split()) == sorted(_BASE_FILES), "grep не видит файлы"

    found = _git("grep", "-nE", _THREAD_PATTERN, "--", *_BASE_FILES)
    assert (found.returncode, found.stdout) == (1, ""), found.stdout or found.stderr

    base = _git("merge-base", "HEAD", "main")
    assert base.returncode == 0, base.stderr
    diff = _git("diff", base.stdout.strip(), "--", "scripts/lifecycle_guards/tables.py")
    assert diff.returncode == 0, diff.stderr
    # К4' (4.2b) снимает запись R4 старого hikvision-плагина: таблица меняется, но строк `camera_device` в правке нет.
    changed = [ln for ln in diff.stdout.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    assert not [ln for ln in changed if "camera_device" in ln], changed
