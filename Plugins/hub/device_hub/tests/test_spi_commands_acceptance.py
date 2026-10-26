"""Слепая приёмка SPI хаба, плагин: команды, генерация, остановка, исполнитель (А1-А9, А10а, А13-А15, А17-А20, А22-А25).

Purpose:
    Строки ``plans/robot-protocol-v2/tasks/SPI.acceptance.md``, которые проверяются через ``DeviceHubPlugin``.
    Обвязка: настоящий плагин на ``make_ctx`` + настоящие ``CommandManager`` / ``ExecutorManager`` / ``RouterManager``;
    драйверы-фейки внедряются публичной ``register_driver_factory`` менеджера (наследники ``BaseDeviceDriver`` и
    «простой объект» без нового контракта). «Супервизор» — поток, зовущий ``plugin._process_conn_queue()`` (как
    существующие тесты хаба). Приватных имён драйвера в файле нет (сторож ``test_no_private_driver_state.py``).
    Имена из ``Services.device_hub.spi`` и ``install_op_commands`` импортируются ВНУТРИ тестов: до реализации их нет,
    и каждый тест докладывает свой красный. Любой вызов, который может повиснуть, идёт под дедлайном (daemon-поток).
    Ожидаемые значения — литералы файла приёмки.

Public API:
    Только тесты ``test_a<N>_*``.

Stability: lite
"""

from __future__ import annotations

import ast
import importlib
import re
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

import Services.device_hub.drivers.robot_driver_v2 as v2pkg
from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.device_hub.drivers.base import BaseDeviceDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

_CALL_S = 20.0
_JOIN_S = 10.0
_CONNECT_S = 60.0

# --------------------------------------------------------------------------------------------------
# Литералы файла приёмки
# --------------------------------------------------------------------------------------------------

# А1: 72 имени
_DEVICE_COMMANDS = (
    "device_list device_describe device_upsert device_upsert_many device_sync_set device_remove device_protocols "
    "device_connect device_disconnect device_read device_write"
).split()
_HIK_COMMANDS = "hik_enum hik_open hik_close hik_get_params hik_set_params hik_release".split()
# 40 команд робота маршрута «драйвер»: 29 прежних + 11 v2
_ROBOT_V1_COMMANDS = (
    "robot_enqueue_job robot_return_job robot_send_test_job robot_abort robot_set_mode robot_jog robot_jog_abort "
    "robot_set_servo robot_set_robot_config robot_get_robot_config robot_get_telemetry robot_read_echo "
    "robot_set_manual_mode robot_clear_queue robot_set_encoder_offset robot_toolchange robot_exchange_log_get "
    "robot_exchange_log_set robot_draw_polyline robot_draw_circle robot_draw_square robot_draw_set_pen "
    "robot_draw_set_speed robot_draw_set_travel robot_draw_set_accel robot_draw_set_pass_size robot_draw_set_overlap "
    "robot_draw_abort robot_draw_progress"
).split()
_ROBOT_V2_COMMANDS = (
    "robot_param_set robot_param_apply robot_stop robot_servo robot_do_set robot_jog_step robot_jog_hold "
    "robot_jog_release robot_point_capture robot_program_run robot_program_abort"
).split()
_ROBOT_DATA_COMMANDS = (
    "robot_param_get_all robot_point_list robot_point_save robot_point_delete robot_frame_list robot_frame_teach "
    "robot_program_list robot_program_get robot_program_save robot_program_delete"
).split()
_VFD_COMMANDS = "vfd_run vfd_set_freq vfd_stop vfd_reset_fault vfd_get_status".split()
_ROBOT_DRIVER_COMMANDS = _ROBOT_V1_COMMANDS + _ROBOT_V2_COMMANDS
ALL_COMMANDS = (
    _DEVICE_COMMANDS + _ROBOT_V1_COMMANDS + _ROBOT_DATA_COMMANDS + _ROBOT_V2_COMMANDS[:] + _VFD_COMMANDS + _HIK_COMMANDS
)

# А3: 21 описание команд робота v2
_DESC_V2 = {
    "robot_param_get_all": "Робот v2: все параметры из файла {device_id} -> params{raw, value}, epoch, rev",
    "robot_point_list": "Робот v2: список точек {device_id} -> points, rev",
    "robot_point_save": "Робот v2: сохранить точку {device_id, point{name, x, y, z, rz, hand, frame?}, base_rev}",
    "robot_point_delete": "Робот v2: удалить точку {device_id, name, base_rev}",
    "robot_frame_list": "Робот v2: список систем координат {device_id} -> frames, rev",
    "robot_frame_teach": "Робот v2: обучить СК по трём точкам {device_id, name, origin, on_x, in_plane, base_rev}",
    "robot_program_list": "Робот v2: имена программ {device_id} -> programs",
    "robot_program_get": "Робот v2: прочитать программу {device_id, name} -> program, rev",
    "robot_program_save": "Робот v2: сохранить программу {device_id, program{name, steps}, base_rev}",
    "robot_program_delete": "Робот v2: удалить программу {device_id, name, base_rev}",
    "robot_param_set": "Робот v2: записать параметр {device_id, name, value, base_rev}",
    "robot_param_apply": "Робот v2: применить параметры класса reinit {device_id}",
    "robot_stop": "Робот v2: стоп {device_id, level: SOFT|HARD|HALT}",
    "robot_servo": "Робот v2: серво {device_id, on: bool}",
    "robot_do_set": "Робот v2: дискретный выход {device_id, ch: 1..16, on: bool}",
    "robot_jog_step": "Робот v2: шаг jog {device_id, dx, dy, dz?, drz?, spd: 1..100}",
    "robot_jog_hold": "Робот v2: удержание jog {device_id, dir: 1..8, spd: 1..100}",
    "robot_jog_release": "Робот v2: отпустить jog {device_id}",
    "robot_point_capture": "Робот v2: запомнить текущую позу как точку {device_id, name, base_rev}",
    "robot_program_run": "Робот v2: запустить программу {device_id, name}",
    "robot_program_abort": "Робот v2: прервать программу {device_id}",
}
# А3 [c2]: 34 остальных
_DESC_REST = {
    "robot_enqueue_job": "Поставить CVT-задание: {device_id, x_mm, y_mm, e_capture?}.",
    "robot_return_job": "Возврат буквы на ленту: {device_id, x_mm, y_mm, z_mm} (координата слота).",
    "robot_send_test_job": "Тестовое CVT-задание: {device_id, x, y}.",
    "robot_abort": "Стоп робота: {device_id, mode: 1|2|3}.",
    "robot_set_mode": "Режим робота: {device_id, mode: cvt|draw|manual}.",
    "robot_jog": "Ручной ход: {device_id, dx, dy, spd?, absolute?} — смещение мм + Override %.",
    "robot_jog_abort": "Прервать ручной ход: {device_id}.",
    "robot_set_servo": "Серво: {device_id, on: bool}.",
    "robot_set_robot_config": "Конфиг робота: {device_id, ...fields}.",
    "robot_get_robot_config": "Прочитать конфиг-блок робота.",
    "robot_get_telemetry": "Телеметрия робота.",
    "robot_read_echo": "Эхо последнего задания.",
    "robot_set_manual_mode": "Ручной режим: {device_id, on: bool}.",
    "robot_clear_queue": "Очистить очередь заданий.",
    "robot_set_encoder_offset": "Подстройка компенсации конвейера: {device_id, lead_mm} (мм вдоль ленты, знаковое).",
    "robot_toolchange": "Смена инструмента: {device_id, target: 0|1|2, timeout?}.",
    "robot_exchange_log_get": (
        "Журнал обмена драйвера: {device_id, since_seq?, limit?}. Работает и при разрыве связи (T5.6)."
    ),
    "robot_exchange_log_set": "Ручки журнала обмена: {device_id, enabled?, periodic?, clear?} (T5.6).",
    "robot_draw_polyline": "Нарисовать полилинию: {device_id, points, ...}.",
    "robot_draw_circle": "Нарисовать окружность: {device_id, cx, cy, r}.",
    "robot_draw_square": "Нарисовать квадрат: {device_id, cx, cy, side}.",
    "robot_draw_set_pen": "Установить перо: {device_id, pen_z}.",
    "robot_draw_set_speed": "Установить скорость рисования (перо по бумаге): {device_id, pct}.",
    "robot_draw_set_travel": "Установить скорость переезда (перо вверх): {device_id, pct}.",
    "robot_draw_set_accel": "Установить ускорение рисования: {device_id, accel} (мм/с²).",
    "robot_draw_set_pass_size": "Установить размер пачки рисования: {device_id, n} (точек на проход).",
    "robot_draw_set_overlap": "Установить overlap: {device_id, overlap}.",
    "robot_draw_abort": "Прервать рисование: {device_id}.",
    "robot_draw_progress": "Прогресс рисования: {device_id}.",
    "vfd_run": "Пуск ПЧ: {device_id, direction?, freq_hz?}.",
    "vfd_set_freq": "Установить частоту: {device_id, freq_hz}.",
    "vfd_stop": "Стоп ПЧ: {device_id}.",
    "vfd_reset_fault": "Сброс аварии ПЧ: {device_id}.",
    "vfd_get_status": "Статус ПЧ: {device_id}.",
}

PLUGIN_SOURCE = Path(__file__).resolve().parents[1] / "plugin.py"


# --------------------------------------------------------------------------------------------------
# Общие помощники
# --------------------------------------------------------------------------------------------------


def spi() -> Any:
    return importlib.import_module("Services.device_hub.spi")


def bounded(fn: Callable[[], Any], deadline_s: float = _CALL_S) -> Any:
    """Вызов в daemon-потоке с join-дедлайном; ошибка потока поднимается в тесте, зависание — ``AssertionError``."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносится в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name="spi-bounded")
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Lines:
    """Строки лога стенда: ``(уровень, текст)``."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.records: list[tuple[str, str]] = []

    def add(self, level: str, message: Any) -> None:
        text = str(message() if callable(message) else message)
        with self.guard:
            self.records.append((level, text))

    def matching(self, level: str | None, needle: str) -> list[str]:
        with self.guard:
            return [m for lvl, m in self.records if (level is None or lvl == level) and needle in m]


class FakeLogger:
    """Слот ``logger`` менеджера команд."""

    def __init__(self, lines: Lines) -> None:
        self.lines = lines

    def debug(self, message: Any, **kw: Any) -> None:
        self.lines.add("DEBUG", message)

    def info(self, message: Any, **kw: Any) -> None:
        self.lines.add("INFO", message)

    def warning(self, message: Any, **kw: Any) -> None:
        self.lines.add("WARNING", message)

    def error(self, message: Any, **kw: Any) -> None:
        self.lines.add("ERROR", message)

    def critical(self, message: Any, **kw: Any) -> None:
        self.lines.add("ERROR", message)


class Proxy:
    """``ctx.state_proxy``: пишет каждый ``set`` / ``merge``."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.calls: list[tuple[str, str, Any]] = []

    def set(self, path: str, data: Any) -> None:
        with self.guard:
            self.calls.append(("set", path, data))

    def merge(self, path: str, data: Any) -> None:
        with self.guard:
            self.calls.append(("merge", path, data))

    def statuses(self, dev: str) -> list[str]:
        """Статусы ``conn`` устройства по порядку; повторы подряд схлопнуты."""
        path = f"devices.state.{dev}.conn"
        with self.guard:
            raw = [d["conn"] for op, p, d in self.calls if op == "set" and p == path and isinstance(d, dict)]
        out: list[str] = []
        for status in raw:
            if not out or out[-1] != status:
                out.append(status)
        return out


class Rig:
    """Плагин на ``make_ctx`` + настоящий ``CommandManager``; реестр — ``tmp_path / "devices.yaml"``."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        executors: dict | None = None,
        plugin_cls: type = DeviceHubPlugin,
        boot: bool = True,
    ) -> None:
        monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)
        self.tmp_path = tmp_path
        self.registry = tmp_path / "devices.yaml"
        self.lines = Lines()
        self.proxy = Proxy()
        self.wm = WorkerManager(manager_name="spi", process=None)
        assert self.wm.initialize() is True
        self.em = ExecutorManager("spi_executors", worker_manager=self.wm)
        assert self.em.initialize() is True
        if executors is not None:
            self.em.load_config(executors)
        self.cm = CommandManager("devices", managers={"logger": FakeLogger(self.lines)}, executors=self.em)
        assert self.cm.initialize() is True
        self.ctx = make_ctx({"registry_path": str(self.registry)}, state_proxy=self.proxy, tmp_registry=self.registry)
        self.ctx.command_manager = self.cm
        self.ctx.health = MagicMock()
        self.plugin = plugin_cls()
        self.factories: list[str] = []
        self.threads: list[threading.Thread] = []
        if boot:
            self.boot()

    def boot(self) -> None:
        bounded(lambda: self.plugin._do_configure(self.ctx))
        bounded(lambda: self.plugin._do_start(self.ctx))

    # --- команды и супервизор ---

    def cmd(self, name: str, data: dict | None = None) -> Any:
        return bounded(lambda: getattr(self.plugin, f"cmd_{name}")(dict(data or {})))

    def drain(self, deadline_s: float = _CONNECT_S) -> None:
        bounded(self.plugin._process_conn_queue, deadline_s)

    def factory(self, kind: str, build: Callable[[Any, Any], Any]) -> None:
        self.plugin._manager.register_driver_factory(kind, build)

    def upsert(self, dev_id: str, kind: str, protocol: str = "", transport: dict | None = None, **extra: Any) -> None:
        entry = {
            "id": dev_id,
            "name": dev_id,
            "kind": kind,
            "protocol": protocol,
            "transport": transport or {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2},
            **extra,
        }
        res = self.cmd("device_upsert", entry)
        assert res["status"] == "ok", res

    def connect(self, dev_id: str) -> Any:
        """Синхронное подключение через менеджер (фейк-драйверы подключаются мгновенно)."""
        return bounded(lambda: self.plugin._manager.connect(dev_id))

    def driver(self, dev_id: str) -> Any:
        return self.plugin._manager.get_driver(dev_id)

    def spawn_thread(self, fn: Callable[[], Any], name: str) -> threading.Thread:
        thread = threading.Thread(target=fn, name=name, daemon=True)
        thread.start()
        self.threads.append(thread)
        return thread

    def close(self) -> None:
        for thread in self.threads:
            thread.join(3.0)
        try:
            bounded(lambda: self.plugin.shutdown(self.ctx), 10.0)
        except BaseException:  # noqa: BLE001 — уборка не подменяет провал теста
            pass
        for mgr in (self.cm, self.em, self.wm):
            try:
                bounded(mgr.shutdown, 10.0)
            except BaseException:  # noqa: BLE001
                pass


@pytest.fixture
def make_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rigs: list[Rig] = []

    def new(sub: str = "main", **kwargs: Any) -> Rig:
        path = tmp_path / sub
        path.mkdir(parents=True, exist_ok=True)
        rig = Rig(path, monkeypatch, **kwargs)
        rigs.append(rig)
        return rig

    yield new
    for rig in reversed(rigs):
        rig.close()


@pytest.fixture
def rig(make_rig: Callable[..., Rig]) -> Rig:
    return make_rig()


# --- драйверы-фейки ---


class Calls:
    """Журнал ``call`` фейк-драйверов: ``(device_id, op, args)``."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.items: list[tuple[str, str, dict]] = []

    def add(self, dev_id: str, op: str, args: dict) -> None:
        with self.guard:
            self.items.append((dev_id, op, dict(args)))

    def last(self) -> tuple[str, str, dict] | None:
        with self.guard:
            return self.items[-1] if self.items else None


class FakeDriver(BaseDeviceDriver):
    """Наследник базы: подключается мгновенно, ``call`` пишет ``(op, args)`` и отвечает ``ok``."""

    kind = "fake"

    def __init__(self, entry: Any, protocol: Any = None, *, calls: Calls | None = None) -> None:
        super().__init__(entry, protocol) if protocol is not None else super().__init__(entry)
        self.calls = calls or Calls()
        self.up = False
        self.disconnect_calls = 0
        self.reply: dict = {"status": "ok"}

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def connect(self) -> bool:
        self.up = True
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.up = False

    @property
    def is_connected(self) -> bool:
        return self.up

    def tick(self, stop_event: Any = None) -> None:
        return None

    def call(self, op: str, args: dict) -> dict:
        self.calls.add(self.entry.id, op, args)
        return dict(self.reply)


class DegradableDriver(FakeDriver):
    """Зависимый драйвер с собственным ``set_degraded() -> True``."""

    def set_degraded(self) -> bool:
        self.up = False
        return True


class PlainObjectDriver:
    """Простой объект: ни ``set_degraded``, ни ``stop_unconfirmed``, ни ``stop_aware``, ни ``request_disconnect``."""

    kind = "plain"

    def __init__(self, entry: Any, protocol: Any = None) -> None:
        self.entry = entry
        self.protocol = protocol
        self.up = False
        self.desired_connected = False
        self.reconnect_exhausted = False
        self.is_initialized = False
        self.stats: dict = {}

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        return True

    def connect(self) -> bool:
        self.up = True
        return True

    def disconnect(self) -> None:
        self.up = False

    @property
    def is_connected(self) -> bool:
        return self.up

    def tick(self, stop_event: Any = None) -> None:
        return None

    def call(self, op: str, args: dict) -> dict:
        return {"status": "ok"}

    def reset_reconnect(self) -> None:
        return None


# --------------------------------------------------------------------------------------------------
# А1 / А2 — состав и регистрация команд
# --------------------------------------------------------------------------------------------------


def test_a1_commands_are_exactly_the_72_names() -> None:
    """А1: ``set(DeviceHubPlugin.commands)`` == 72 имени из файла приёмки."""
    expected = set(ALL_COMMANDS)
    assert len(ALL_COMMANDS) == 72 and len(expected) == 72, "литерал теста собран неверно"
    assert set(DeviceHubPlugin.commands) == expected


def test_a2_all_72_registered_in_real_command_manager_without_noise(rig: Rig) -> None:
    """А2: после ``_do_configure`` + ``_do_start`` у всех 72 команд есть запись; в логе нет повторов и отказов."""
    missing = [name for name in ALL_COMMANDS if rig.cm.get_command_info(name) is None]
    assert missing == [], missing
    assert rig.lines.matching(None, "already exists") == []
    assert rig.lines.matching(None, "Failed to register command") == []
    assert rig.lines.matching(None, "registered successfully") != [], "недостижимо: лог регистрации пуст"


# --------------------------------------------------------------------------------------------------
# А3 — описания в каталоге
# --------------------------------------------------------------------------------------------------


def _description(rig: Rig, name: str) -> Any:
    info = rig.cm.get_command_info(name)
    assert info is not None, f"команда {name} не зарегистрирована"
    return (info.get("metadata") or {}).get("description")


@pytest.mark.parametrize("name", list(_DESC_V2))
def test_a3_robot_v2_description_is_literal(rig: Rig, name: str) -> None:
    """А3: 21 команда робота v2 несёт литеральное описание."""
    assert _description(rig, name) == _DESC_V2[name]


@pytest.mark.parametrize("name", list(_DESC_REST))
def test_a3_c2_remaining_34_descriptions_are_literal(rig: Rig, name: str) -> None:
    """А3 ``[c2]``: 34 остальных команды несут литеральное описание."""
    assert _description(rig, name) == _DESC_REST[name]


# --------------------------------------------------------------------------------------------------
# А4-А7 — маршруты и тексты ответов
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["robot_stop", "robot_point_list", "robot_exchange_log_get", "vfd_run"])
def test_a4_missing_device_id_literal_error(rig: Rig, name: str) -> None:
    """А4: вызов без ``device_id`` — ``{"status": "error", "message": "device_id обязателен"}``."""
    assert rig.cmd(name, {}) == {"status": "error", "message": "device_id обязателен"}


def test_a5_robot_command_for_vfd_device_names_expected_kind(rig: Rig) -> None:
    """А5: ``cmd_robot_stop`` для устройства вида ``vfd`` — ошибка, в тексте ``ожидается 'robot'``."""
    rig.upsert("v1", "vfd", "gd20_bridge", {"type": "bridge", "bridge": "r1"})
    res = rig.cmd("robot_stop", {"device_id": "v1"})
    assert res["status"] == "error", res
    assert "ожидается 'robot'" in res["message"], res


def test_a5_vfd_command_for_robot_device_names_expected_kind(rig: Rig) -> None:
    """А5: ``cmd_vfd_run`` для робота — ошибка, в тексте ``ожидается 'vfd'``."""
    rig.upsert("r1", "robot", "delta_v2")
    res = rig.cmd("vfd_run", {"device_id": "r1"})
    assert res["status"] == "error", res
    assert "ожидается 'vfd'" in res["message"], res


def test_a5_pair_right_kind_does_not_get_the_kind_error(rig: Rig) -> None:
    """А5, пара: команда своего вида (робот не подключён) отвечает другой ошибкой — без «ожидается»."""
    rig.upsert("r1", "robot", "delta_v2")
    res = rig.cmd("robot_stop", {"device_id": "r1"})
    assert "ожидается" not in str(res.get("message", "")), res


def test_a6_exchange_log_get_for_created_unconnected_robot_is_ok(rig: Rig) -> None:
    """А6: у созданного, не подключённого робота ``delta_v2`` — ``status == "ok"``."""
    rig.upsert("r1", "robot", "delta_v2", {"type": "tcp", "host": "127.0.0.1", "port": free_port(), "unit_id": 2})
    assert rig.cmd("device_connect", {"device_id": "r1"})["status"] == "ok"
    rig.drain()
    assert rig.driver("r1") is not None, "настройка теста: драйвер не создан"
    assert rig.driver("r1").is_connected is False, "настройка теста: робот подключился"
    assert rig.cmd("robot_exchange_log_get", {"device_id": "r1"})["status"] == "ok"


def test_a6_exchange_log_get_without_driver_literal_error(rig: Rig) -> None:
    """А6: у робота без созданного драйвера — ``{"status": "error", "message": "журнала нет: драйвер не создан"}``."""
    rig.upsert("r1", "robot", "delta_v2")
    assert rig.driver("r1") is None, "настройка теста: драйвер уже создан"
    assert rig.cmd("robot_exchange_log_get", {"device_id": "r1"}) == {
        "status": "error",
        "message": "журнала нет: драйвер не создан",
    }


def test_a7_point_list_of_unconnected_robot_with_store_is_ok(rig: Rig) -> None:
    """А7: ``robot_point_list`` у не подключённого ``delta_v2`` с хранилищем — ``ok``, ключи ``points``, ``rev``."""
    rig.upsert("r1", "robot", "delta_v2")
    res = rig.cmd("robot_point_list", {"device_id": "r1"})
    assert res["status"] == "ok", res
    assert "points" in res and "rev" in res, res


def test_a7_servo_of_unconnected_robot_literal_error(rig: Rig) -> None:
    """А7: ``robot_servo`` у него же — ``status == "error"``, ``message == "Устройство 'r1' не подключено"``."""
    rig.upsert("r1", "robot", "delta_v2")
    res = rig.cmd("robot_servo", {"device_id": "r1", "on": True})
    assert res["status"] == "error", res
    assert res["message"] == "Устройство 'r1' не подключено", res


# --------------------------------------------------------------------------------------------------
# А8 — AST исходника плагина (только имена узлов)
# --------------------------------------------------------------------------------------------------


def _plugin_class() -> ast.ClassDef:
    tree = ast.parse(PLUGIN_SOURCE.read_text(encoding="utf-8"))
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DeviceHubPlugin")


def _assigned_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Assign):
        names += [t.id for t in node.targets if isinstance(t, ast.Name)]
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.append(node.target.id)
    return names


def test_a8_exactly_17_cmd_functions_11_device_and_6_hik() -> None:
    """А8: в классе ровно 17 ``FunctionDef`` ``cmd_*`` (11 ``cmd_device_*`` + 6 ``cmd_hik_*``)."""
    defs = [n.name for n in ast.walk(_plugin_class()) if isinstance(n, ast.FunctionDef) and n.name.startswith("cmd_")]
    assert len(defs) == 17, sorted(defs)
    assert len([d for d in defs if d.startswith("cmd_device_")]) == 11, sorted(defs)
    assert len([d for d in defs if d.startswith("cmd_hik_")]) == 6, sorted(defs)


def test_a8_no_robot_or_vfd_cmd_nodes_in_class() -> None:
    """А8: ни одного ``FunctionDef`` / ``Assign`` / ``AnnAssign`` с именем ``cmd_robot_*`` / ``cmd_vfd_*``."""
    forbidden = ("cmd_robot_", "cmd_vfd_")
    cls = _plugin_class()
    names = [n.name for n in ast.walk(cls) if isinstance(n, ast.FunctionDef)]
    for node in ast.walk(cls):
        names += _assigned_names(node)
    assert [n for n in names if n.startswith(forbidden)] == []
    assert any(n.startswith("cmd_device_") for n in names), "недостижимо: класс разобран пустым"


def test_a8_commands_literal_has_no_robot_or_vfd_keys() -> None:
    """А8: в литерале словаря ``commands`` тела класса нет ключей ``robot_*`` и ``vfd_*``."""
    keys: list[str] = []
    for node in _plugin_class().body:
        if "commands" in _assigned_names(node) and isinstance(getattr(node, "value", None), ast.Dict):
            keys += [k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    assert "device_list" in keys, f"литерал commands с device_* не найден в теле класса: {keys}"
    assert [k for k in keys if k.startswith(("robot_", "vfd_"))] == []


# --------------------------------------------------------------------------------------------------
# А9 / А10(а) — генерация команд из источников
# --------------------------------------------------------------------------------------------------


def _fake_source() -> Any:
    mod = spi()
    return mod.OpSource(
        prefix="fake", kind="fake", route="driver", ops=(mod.OpSpec(name="ping", description="Фейк: пинг"),)
    )


class PingDriver(FakeDriver):
    kind = "fake"

    def call(self, op: str, args: dict) -> dict:
        assert op == "ping"
        return {"status": "ok", "pong": 1}


def test_a9_install_op_commands_extends_subclass_only() -> None:
    """А9: ``install_op_commands(Sub, ...)`` — ``fake_ping`` в ``Sub.commands``; база прежняя: 72 имени, без метода."""
    plugin_mod = importlib.import_module("Plugins.hub.device_hub.plugin")

    class Sub(DeviceHubPlugin):
        pass

    plugin_mod.install_op_commands(Sub, [_fake_source()])
    assert "fake_ping" in Sub.commands
    assert set(DeviceHubPlugin.commands) == set(ALL_COMMANDS)
    assert hasattr(DeviceHubPlugin, "cmd_fake_ping") is False


def test_a9_generated_command_reaches_fake_driver_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """А9: фабрика ``fake`` в менеджере ``Sub``; ``cmd_fake_ping`` → ``{"status": "ok", "pong": 1}``."""
    plugin_mod = importlib.import_module("Plugins.hub.device_hub.plugin")

    class Sub(DeviceHubPlugin):
        pass

    plugin_mod.install_op_commands(Sub, [_fake_source()])
    rig = Rig(tmp_path, monkeypatch, plugin_cls=Sub)
    try:
        rig.factory("fake", lambda entry, proto: PingDriver(entry, proto))
        rig.upsert("f1", "fake")
        assert rig.connect("f1") is True
        assert rig.driver("f1").is_connected
        assert rig.cmd("fake_ping", {"device_id": "f1"}) == {"status": "ok", "pong": 1}
    finally:
        rig.close()


def test_a10a_install_op_commands_with_taken_name_raises() -> None:
    """А10(а): ``install_op_commands`` с именем, уже лежащим в ``commands`` класса, — ``ValueError``."""
    mod = spi()
    plugin_mod = importlib.import_module("Plugins.hub.device_hub.plugin")

    class Sub(DeviceHubPlugin):
        pass

    taken = mod.OpSource(
        prefix="device", kind="fake", route="driver", ops=(mod.OpSpec(name="list", description="Фейк: список"),)
    )
    with pytest.raises(ValueError):
        plugin_mod.install_op_commands(Sub, [taken])


# --------------------------------------------------------------------------------------------------
# А19 — каждая команда драйверного маршрута доходит до call как (op без префикса, args без device_id)
# --------------------------------------------------------------------------------------------------


def _drive_all(rig: Rig, kind: str, protocol: str, commands: list[str], prefix: str) -> tuple[list[str], int]:
    calls = Calls()
    rig.factory(kind, lambda entry, proto: FakeDriver(entry, proto, calls=calls))
    rig.upsert("d1", kind, protocol)
    assert rig.connect("d1") is True
    assert rig.driver("d1").is_connected, "настройка теста: фейк не подключён"
    bad: list[str] = []
    for name in commands:
        before = len(calls.items)
        rig.cmd(name, {"device_id": "d1", "k": 1})
        got = calls.items[before:]
        expected_op = name.removeprefix(prefix)
        if got != [("d1", expected_op, {"k": 1})]:
            bad.append(f"{name}: ожидали [('d1', {expected_op!r}, {{'k': 1}})], получили {got}")
    return bad, len(commands)


@pytest.mark.parametrize("protocol", ["delta_v2", "delta_universal3"])
def test_a19_robot_driver_route_commands_call_driver_with_stripped_op(rig: Rig, protocol: str) -> None:
    """А19: 40 команд робота маршрута «драйвер» → ``call(op без robot_, {"k": 1})`` (протоколы v2 и v1)."""
    bad, checked = _drive_all(rig, "robot", protocol, _ROBOT_DRIVER_COMMANDS, "robot_")
    assert checked == 40
    assert bad == [], "\n".join(bad)


def test_a19_vfd_commands_call_driver_with_stripped_op(rig: Rig) -> None:
    """А19: 5 команд ``vfd_*`` → ``call(op без vfd_, {"k": 1})``."""
    bad, checked = _drive_all(rig, "vfd", "gd20_bridge", _VFD_COMMANDS, "vfd_")
    assert checked == 5
    assert bad == [], "\n".join(bad)


# --------------------------------------------------------------------------------------------------
# А13 — device_read без транспорта регистров
# --------------------------------------------------------------------------------------------------


def test_a13_device_read_without_register_transport_literal_error(rig: Rig) -> None:
    """А13: ``device_read`` у подключённого ``vfd`` (наследник базы, протокол есть, транспорта нет) — литерал."""
    rig.factory("vfd", lambda entry, proto: FakeDriver(entry, proto))
    rig.upsert("v1", "vfd", "gd20_bridge")
    assert rig.connect("v1") is True
    assert rig.driver("v1").is_connected
    # имя регистра ``status`` (``access: r``) есть в протоколе; ключ аргумента в приёмке не назван — даны все вероятные
    arg = "status"
    res = rig.cmd("device_read", {"device_id": "v1", "register": arg, "name": arg, "reg": arg, "names": [arg]})
    assert res == {"status": "error", "message": "у устройства нет транспорта регистров"}


# --------------------------------------------------------------------------------------------------
# А20 — носитель моста отключается: деградация зависимых
# --------------------------------------------------------------------------------------------------

_BRIDGE = {"type": "bridge", "bridge": "r1"}


def _carrier_with(rig: Rig, deps: dict[str, Callable[[Any, Any], Any]]) -> None:
    """Носитель ``r1`` (подключён) и зависимые ``deps`` (id → фабрика вида ``vfd``), все подключены."""
    rig.factory("robot", lambda entry, proto: FakeDriver(entry, proto))
    rig.upsert("r1", "robot", "delta_universal3")
    assert rig.connect("r1") is True
    factories = dict(deps)
    rig.factory("vfd", lambda entry, proto: factories[entry.id](entry, proto))
    for dev_id in deps:
        rig.upsert(dev_id, "vfd", "gd20_bridge", _BRIDGE)
        assert rig.connect(dev_id) is True, dev_id


def _disconnect_carrier(rig: Rig) -> Any:
    res = rig.cmd("device_disconnect", {"device_id": "r1"})
    rig.drain()
    return res


def test_a20_degradable_dependent_gets_disconnected_publication(rig: Rig) -> None:
    """А20: зависимый с ``set_degraded() -> True`` получает ``conn`` = ``{"conn": "disconnected"}``."""
    _carrier_with(rig, {"d1": lambda e, p: DegradableDriver(e, p)})
    mark = len(rig.proxy.calls)
    assert _disconnect_carrier(rig)["status"] == "ok"
    published = [d for op, path, d in rig.proxy.calls[mark:] if op == "set" and path == "devices.state.d1.conn"]
    assert {"conn": "disconnected"} in published, rig.proxy.calls[mark:]


def test_a20_plain_base_dependent_gets_no_publication_and_no_disconnect(rig: Rig) -> None:
    """А20: наследник базы без своего ``set_degraded`` — публикации нет, его ``disconnect()`` не вызван."""
    _carrier_with(rig, {"d1": lambda e, p: FakeDriver(e, p)})
    dependent = rig.driver("d1")
    mark = len(rig.proxy.calls)
    assert _disconnect_carrier(rig)["status"] == "ok"
    published = [d for op, path, d in rig.proxy.calls[mark:] if op == "set" and path == "devices.state.d1.conn"]
    assert published == [], published
    assert dependent.disconnect_calls == 0


def test_a20_object_without_set_degraded_does_not_block_the_next_dependent(rig: Rig) -> None:
    """А20: первый зависимый — простой объект (AttributeError), второй всё равно получает ``disconnected``."""
    _carrier_with(
        rig,
        {"d1": lambda e, p: PlainObjectDriver(e, p), "d2": lambda e, p: DegradableDriver(e, p)},
    )
    mark = len(rig.proxy.calls)
    res = _disconnect_carrier(rig)
    assert res["status"] == "ok", res
    published = [d for op, path, d in rig.proxy.calls[mark:] if op == "set" and path == "devices.state.d2.conn"]
    assert {"conn": "disconnected"} in published, rig.proxy.calls[mark:]


# --------------------------------------------------------------------------------------------------
# А14 — «Отключить» посреди connect; MagicMock-драйвер
# --------------------------------------------------------------------------------------------------


class _Gate:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()


class _BarrierTransport:
    """Транспорт: ``connect`` встаёт на барьер до того, как связь считается поднятой."""

    def __init__(self, gate: _Gate) -> None:
        self.gate = gate
        self.is_connected = False

    def connect(self) -> bool:
        self.gate.entered.set()
        self.gate.release.wait(10.0)
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def read_registers(self, _address: int, _count: int) -> list[int]:
        return [0] * 32


def test_a14_disconnect_mid_connect_sets_pending_and_ends_disconnected(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """А14: ``device_disconnect`` посреди ``connect`` — ``disconnect_pending`` True; итог ``disconnected``."""
    gate = _Gate()

    class V2(RobotDriverV2):
        def __init__(self, entry: Any, protocol: Any = None, **kw: Any) -> None:
            super().__init__(entry, protocol, transport=_BarrierTransport(gate), **kw)

    monkeypatch.setattr(v2pkg, "RobotDriverV2", V2)
    rig.upsert("r1", "robot", "delta_v2", params={"poll_interval_s": 0.05})
    assert rig.cmd("device_connect", {"device_id": "r1"})["status"] == "ok"
    sup = rig.spawn_thread(rig.plugin._process_conn_queue, "spi-sup")
    try:
        assert gate.entered.wait(5.0), "окно недостижимо: connect не дошёл до транспорта"
        assert sup.is_alive(), "супервизор не стоит в connect"
        assert rig.cmd("device_disconnect", {"device_id": "r1"})["status"] == "ok"
        assert rig.driver("r1").disconnect_pending is True
    finally:
        gate.release.set()
    sup.join(_JOIN_S)
    assert not sup.is_alive(), "супервизор не вышел после отпускания барьера"
    rig.drain()
    assert rig.proxy.statuses("r1")[-1] == "disconnected", rig.proxy.statuses("r1")


def test_a14_magicmock_driver_connect_false_publishes_error_not_disconnecting(rig: Rig) -> None:
    """А14: ``MagicMock``-драйвер, ``connect`` → ``False`` — ``{"conn": "error"}``, не ``disconnecting``."""
    mock = MagicMock()
    mock.connect.return_value = False
    rig.factory("robot", lambda entry, proto: mock)
    rig.upsert("r1", "robot", "delta_universal3")
    assert rig.cmd("device_connect", {"device_id": "r1"})["status"] == "ok"
    rig.drain()
    statuses = rig.proxy.statuses("r1")
    assert statuses and statuses[-1] == "error", statuses
    assert "disconnecting" not in statuses, statuses


# --------------------------------------------------------------------------------------------------
# А15 / А24 / А25 — остановка плагина и «Отключить»
# --------------------------------------------------------------------------------------------------


class _ThreadNames:
    """Имена всех потоков, запущенных за время окна (подмена ``Thread.start`` на запись имени)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.names: list[str] = []
        self.guard = threading.Lock()
        original = threading.Thread.start
        recorder = self

        def start(thread: threading.Thread, *a: Any, **kw: Any) -> Any:
            with recorder.guard:
                recorder.names.append(thread.name)
            return original(thread, *a, **kw)

        monkeypatch.setattr(threading.Thread, "start", start)


def test_a15_stop_threads_only_for_the_robot(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """А15: остановка плагина с роботом ``delta_v2`` и ПЧ — поток ``stop-<id>-<k>`` создан только для робота."""

    class Connected(RobotDriverV2):
        """Настоящий драйвер v2 (stop_aware), подключённый без сети."""

        def connect(self) -> bool:
            self.up = True
            return True

        def disconnect(self) -> None:
            self.up = False

        @property
        def is_connected(self) -> bool:
            return getattr(self, "up", False)

    rig.factory("robot", lambda entry, proto: Connected(entry, proto))
    rig.factory("vfd", lambda entry, proto: FakeDriver(entry, proto))
    rig.upsert("r1", "robot", "delta_v2")
    rig.upsert("v1", "vfd", "gd20_bridge")
    assert rig.connect("r1") is True and rig.connect("v1") is True
    seen = _ThreadNames(monkeypatch)
    bounded(lambda: rig.plugin.shutdown(rig.ctx), 15.0)
    stop_names = [n for n in seen.names if re.search(r"(?:^|/)stop-.+-\d+$", n)]
    ids = {re.search(r"(?:^|/)stop-(.+)-\d+$", n).group(1) for n in stop_names}
    assert ids == {"r1"}, f"потоки остановки: {stop_names}; все потоки окна: {seen.names}"


def test_a24_shutdown_with_plain_object_and_base_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """А24: простой объект и наследник базы — ``shutdown`` без исключения, ``disconnect()`` наследника, реестр цел."""
    rig = Rig(tmp_path, monkeypatch)
    try:
        rig.factory("robot", lambda entry, proto: PlainObjectDriver(entry, proto))
        rig.factory("vfd", lambda entry, proto: FakeDriver(entry, proto))
        rig.upsert("p1", "robot", "delta_universal3")
        rig.upsert("b1", "vfd", "gd20_bridge")
        assert rig.connect("p1") is True and rig.connect("b1") is True
        based = rig.driver("b1")
        assert based.is_connected
        bounded(lambda: rig.plugin.shutdown(rig.ctx), 15.0)
        assert based.disconnect_calls >= 1, "disconnect() наследника базы не вызван"
        saved = yaml.safe_load(rig.registry.read_text(encoding="utf-8"))
        assert {d["id"] for d in saved["devices"]} == {"p1", "b1"}, saved
    finally:
        rig.close()


class RaisingRequestDriver(FakeDriver):
    """``request_disconnect()`` бросает ``RuntimeError``."""

    def request_disconnect(self) -> None:
        raise RuntimeError("request_disconnect: сбой")


def test_a25_request_disconnect_error_is_reported_and_disconnect_completes(rig: Rig) -> None:
    """А25: ``request_disconnect()`` бросает — ``disconnecting``, итог ``disconnected``, ``report_error``."""
    rig.factory("robot", lambda entry, proto: RaisingRequestDriver(entry, proto))
    rig.upsert("r1", "robot", "delta_universal3")
    assert rig.connect("r1") is True
    res = rig.cmd("device_disconnect", {"device_id": "r1"})
    assert res == {"status": "ok", "conn": "disconnecting"}, res
    rig.drain()
    assert rig.proxy.statuses("r1")[-1] == "disconnected", rig.proxy.statuses("r1")
    contexts = [c.kwargs.get("context") for c in rig.ctx.health.report_error.call_args_list]
    assert "device_hub.request_disconnect" in contexts, contexts


# --------------------------------------------------------------------------------------------------
# А17 / А18 / А22 / А23 — исполнитель device_io и путь роутера
# --------------------------------------------------------------------------------------------------


class _Process:
    """Хозяин роутера: имя и менеджер команд."""

    def __init__(self, name: str, command_manager: Any) -> None:
        self.name = name
        self.command_manager = command_manager


class _QueueRegistry:
    def send_to_queue(self, target: str, qtype: str, msg: dict, timeout: float = 0.0, on_evict: Any = None) -> bool:
        return True


class RouterPath:
    """Роутер процесса с настоящим ``CommandManager``; ответы перехвачены на границе ``send``."""

    def __init__(self, rig: Rig) -> None:
        self.router = RouterManager(manager_name="devices", queue_registry=_QueueRegistry())
        self.router.process = _Process("devices", rig.cm)
        self.sent: list[dict] = []
        self.replies: list[tuple[Any, str]] = []  # (результат, имя потока ответа)
        self.done = threading.Event()
        original = self.router.reply_to_request
        outer = self

        def reply_to_request(original_msg: Any, result: Any, *a: Any, **kw: Any) -> Any:
            outer.replies.append((result, threading.current_thread().name))
            try:
                return original(original_msg, result, *a, **kw)
            finally:
                outer.done.set()

        self.router.reply_to_request = reply_to_request  # type: ignore[method-assign]
        self.router.send = lambda msg: self.sent.append(msg)  # type: ignore[method-assign]

    def request(self, command: str, data: dict, deadline_s: float = 10.0) -> None:
        """Входящая команда по пути роутера, из потока ``router-thread``; ждёт ответ."""
        message = {"type": "command", "command": command, "data": data, "sender": "gui", "request_id": "cid-1"}
        worker = threading.Thread(
            target=lambda: self.router._dispatch_command(message), name="router-thread", daemon=True
        )
        worker.start()
        worker.join(deadline_s)
        assert not worker.is_alive(), "путь роутера завис"
        assert self.done.wait(deadline_s), "ответ инициатору не ушёл"


def test_a17_point_list_through_router_runs_off_router_thread(make_rig: Callable[..., Rig]) -> None:
    """А17: ``executors = {"device_io": {}}`` — ``robot_point_list`` по пути роутера: один ответ вне роутера."""
    rig = make_rig(executors={"device_io": {}})
    rig.upsert("r1", "robot", "delta_v2")
    path = RouterPath(rig)
    path.request("robot_point_list", {"device_id": "r1"})
    time.sleep(0.2)  # лишний ответ, если он есть, успел бы прийти
    assert len(path.replies) == 1, path.replies
    result, reply_thread = path.replies[0]
    assert result["status"] == "ok", result
    assert reply_thread != "router-thread", f"обработчик исполнен на потоке роутера: {reply_thread}"
    assert len(path.sent) == 1, path.sent


def test_a18_executor_metadata_on_data_commands_only(make_rig: Callable[..., Rig]) -> None:
    """А18: у ``robot_point_list`` вместе ``executor``, ``key_from``, ``description``; у остальных нет ``executor``."""
    rig = make_rig(executors={"device_io": {}})
    metadata = (rig.cm.get_command_info("robot_point_list") or {}).get("metadata") or {}
    assert metadata.get("executor") == "device_io", metadata
    assert metadata.get("key_from") == "device_id", metadata
    assert metadata.get("description") == "Робот v2: список точек {device_id} -> points, rev", metadata
    for name in ("robot_stop", "robot_jog_hold", "vfd_stop"):
        other = (rig.cm.get_command_info(name) or {}).get("metadata")
        assert other is not None, f"{name} не зарегистрирована"
        assert "executor" not in other, (name, other)


def test_a22_point_list_without_device_id_through_router_key_missing(make_rig: Callable[..., Rig]) -> None:
    """А22: ``robot_point_list`` без ``device_id`` по пути роутера — отказ ``key_missing``."""
    rig = make_rig(executors={"device_io": {}})
    path = RouterPath(rig)
    path.request("robot_point_list", {})
    assert len(path.replies) == 1, path.replies
    assert path.replies[0][0] == {"success": False, "error": "key_missing", "command": "robot_point_list"}


def test_a23_without_executors_command_registered_sync_one_warning(make_rig: Callable[..., Rig]) -> None:
    """А23: без секции ``executors`` — команда зарегистрирована, вызов синхронный, ровно один WARNING."""
    rig = make_rig()  # менеджер исполнителей пуст: ``device_io`` не найден
    rig.upsert("r1", "robot", "delta_v2")
    assert rig.cm.get_command_info("robot_point_list") is not None
    result = bounded(lambda: rig.cm.handle_command({"command": "robot_point_list", "data": {"device_id": "r1"}}))
    assert result["status"] == "ok", result
    expected = "Command 'robot_point_list' не зарегистрирована: исполнитель 'device_io' не найден"
    assert len(rig.lines.matching("WARNING", expected)) == 1, rig.lines.records
    assert len(rig.lines.matching("WARNING", "robot_point_list")) == 1, rig.lines.matching(
        "WARNING", "robot_point_list"
    )
    assert rig.lines.matching("WARNING", "исполнитель не принят") == []
