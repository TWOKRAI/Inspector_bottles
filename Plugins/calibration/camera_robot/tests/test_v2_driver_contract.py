"""Слепые приёмочные тесты T5.4, часть 3: камера <-> робот с драйвером v2 (C1-C3).

Purpose:
    Закрепить по файлу приёмки (критерии C1-C3), что мастер ``CameraRobotCalibrationPlugin`` работает с НАСТОЯЩИМ
    ``RobotDriverV2`` против sim v2: контракт телеметрии, пять точек роботом, те же ключи телеметрии, что у v1.
    Образец - ``test_sim_integration.py`` (там драйвер v1). Файлы плагина ``camera_robot`` не правятся.

Как устроено:
    * Стенд - ``E2eRig`` (sim v2 по TCP) + ``RobotDriverV2`` в области потоков ``open_scope``; драйвер v1 - против
      ``SimRobotServer`` v1 (как в образце).
    * Адаптер «``DeviceHubClient`` -> драйвер» подставляется публичным именем ``DeviceHubClient`` модуля плагина
      (``monkeypatch.setattr``); рабочий поток мастера берётся из аргументов ``create_worker`` в ``start`` и
      запускается в daemon-потоке; состояние мастера читается из публикаций ``state_proxy`` (приватных атрибутов
      плагина и драйвера нет).
    * Движение робота - публичными операциями драйвера: ``servo``, ``jog_step``; готовность позы - опросом
      ``get_telemetry`` с дедлайном. Любое ожидание и любой блокирующий вызов ограничены дедлайном.
    * Ожидаемые значения - литералы приёмки: дом sim (300, -210, -40) мм, допуск 0.5 мм, шаг <= 20 мм.

Public API:
    Только тесты ``test_c<N>_*``.

Stability: lite
"""

from __future__ import annotations

import math
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

import Plugins.calibration.camera_robot.plugin as camera_plugin_module
from Plugins.calibration.camera_robot.plugin import CameraRobotCalibrationPlugin
from multiprocess_framework.modules.base_manager import open_scope
from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.server.sim_robot import SimRobotServer
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")

_CALL_S = 20.0
_CONNECT_S = 60.0
_REACH_TOL_MM = 0.5
_HOME = (300.0, -210.0, -40.0)  # дом sim v2, мм

# 5 синтетических центров (как будто circle_detector нашёл 5 точек) - образец test_sim_integration.py
_DETECTIONS = [
    {"center": [100.0, 80.0], "radius": 20},
    {"center": [540.0, 90.0], "radius": 20},
    {"center": [560.0, 420.0], "radius": 20},
    {"center": [90.0, 430.0], "radius": 20},
    {"center": [320.0, 250.0], "radius": 20},
]

# Пять точек роботом: относительные шаги jog_step (<= 20 мм каждый) от дома (300, -210); цели - абсолютные мм.
# Все внутри зоны sim по умолчанию (радиус 100..600, Z -150..0): радиус от основания ~ 340..390 мм, Z не меняется.
_STEPS = [
    (20.0, 0.0, (320.0, -210.0)),
    (0.0, 20.0, (320.0, -190.0)),
    (-20.0, 0.0, (300.0, -190.0)),
    (-15.0, -10.0, (285.0, -200.0)),
    (15.0, -10.0, (300.0, -210.0)),
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait(predicate: Callable[[], bool], timeout: float = 10.0, step: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def _entry_v2(port: int) -> DeviceEntry:
    return DeviceEntry(
        id="robot_main",
        name="sim v2",
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": 2},
        params={},
    )


@pytest.fixture
def v2_driver() -> Iterator[RobotDriverV2]:
    """Настоящий ``RobotDriverV2`` против sim v2 (``E2eRig``), подключённый, в области потоков теста."""
    with E2eRig() as rig:
        scope = open_scope("t54_camera", budget_s=2.5)
        drv = RobotDriverV2(_entry_v2(rig.port), None, publish=lambda _path, _payload: None, spawn=scope.spawn)
        try:
            assert bounded(drv.connect, _CONNECT_S) is True, "драйвер v2 не подключился к sim"
            drv.desired_connected = True
            yield drv
        finally:
            for fn in (drv.disconnect, scope.close):
                try:
                    bounded(fn, _CALL_S)
                except Exception:  # noqa: BLE001 - уборка не подменяет исключение теста
                    pass


@pytest.fixture
def v1_driver() -> Iterator[RobotDriver]:
    """Драйвер v1 против sim v1 (как в образце ``test_sim_integration.py``)."""
    server = SimRobotServer("127.0.0.1", _free_port())
    server.start()
    time.sleep(0.5)
    entry = DeviceEntry(
        id="robot_v1",
        name="sim v1",
        kind="robot",
        protocol="delta_universal3",
        transport={"type": "tcp", "host": server.host, "port": server.port, "unit_id": 2},
        params={"word_order": "little", "telemetry_interval_s": 0.1},
    )
    drv = RobotDriver(entry, protocol=None)
    try:
        assert drv.connect(), "не удалось подключиться к sim v1"
        yield drv
    finally:
        drv.disconnect()
        server.stop()


def _telemetry(drv: Any) -> dict:
    return bounded(lambda: drv.call("get_telemetry", {}), _CALL_S)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --------------------------------------------------------------------------------------------------
# C1 - контракт телеметрии
# --------------------------------------------------------------------------------------------------


def test_c1_v2_telemetry_reply_has_numeric_pose(v2_driver: RobotDriverV2) -> None:
    """C1: ``get_telemetry`` -> ``status == "ok"``, ``telemetry`` с числами ``x_mm``/``y_mm``/``z_mm``/``rz_deg``."""
    res = _telemetry(v2_driver)
    assert res["status"] == "ok", res
    tel = res["telemetry"]
    assert isinstance(tel, dict)
    for key in ("x_mm", "y_mm", "z_mm", "rz_deg"):
        assert key in tel, f"нет {key}: {sorted(tel)}"
        assert _is_number(tel[key]), f"{key}={tel[key]!r} не число"


def test_c1_v2_telemetry_pose_is_sim_home_in_mm(v2_driver: RobotDriverV2) -> None:
    """C1: поза свежего sim v2 - дом (300, -210, -40) мм (единицы - мм, не десятые доли)."""
    tel = _telemetry(v2_driver)["telemetry"]
    assert (tel["x_mm"], tel["y_mm"], tel["z_mm"]) == pytest.approx(_HOME, abs=_REACH_TOL_MM)


def test_c1_v2_encoder_is_int_and_grows(v2_driver: RobotDriverV2) -> None:
    """C1: ``encoder`` - ``int`` (не ``bool``); после хода ленты sim он больше прежнего."""
    first = _telemetry(v2_driver)["encoder"]
    assert type(first) is int
    assert _wait(lambda: _telemetry(v2_driver)["encoder"] > first, timeout=10.0), "энкодер sim v2 не растёт"


# --------------------------------------------------------------------------------------------------
# C2 - мастер камера<->робот на драйвере v2
# --------------------------------------------------------------------------------------------------


class _Snapshots:
    """``ctx.state_proxy``: копит каждую публикацию прогресса мастера (``set`` / ``merge``)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: list[dict] = []

    def set(self, _path: str, data: Any) -> None:
        with self._lock:
            self.items.append(dict(data))

    def merge(self, path: str, data: Any) -> None:  # pragma: no cover - мастер пишет через set
        self.set(path, data)

    def last(self) -> dict:
        with self._lock:
            return dict(self.items[-1]) if self.items else {}

    def errors(self) -> list[Any]:
        with self._lock:
            return [s.get("error") for s in self.items if s.get("error")]


class _V2HubAdapter:
    """Адаптер «``DeviceHubClient`` -> драйвер v2»: ``robot_get_telemetry`` идёт в настоящий драйвер, ПЧ - заглушка."""

    def __init__(self, driver: RobotDriverV2) -> None:
        self._driver = driver
        self.telemetry_calls = 0

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        if command == "robot_get_telemetry":
            self.telemetry_calls += 1
            return self._driver.call("get_telemetry", args or {})
        if command in ("vfd_run", "vfd_stop", "vfd_set_freq"):
            return {"status": "ok"}
        return {"status": "error", "message": f"unsupported {command}"}


def _wait_pose(drv: RobotDriverV2, target: tuple[float, float], timeout: float = 15.0) -> tuple[float, float]:
    """Ждать, пока поза в ``get_telemetry`` дойдёт до цели (+-0.5 мм) и робот остановится; вернуть позу."""
    seen: dict[str, Any] = {}

    def reached() -> bool:
        tel = _telemetry(drv)["telemetry"]
        seen.update(tel)
        return (
            abs(tel["x_mm"] - target[0]) <= _REACH_TOL_MM
            and abs(tel["y_mm"] - target[1]) <= _REACH_TOL_MM
            and tel["moving"] is False
        )

    assert _wait(reached, timeout=timeout, step=0.05), f"поза не дошла до {target}: {seen}"
    return float(seen["x_mm"]), float(seen["y_mm"])


def test_c2_wizard_collects_five_robot_points_with_v2_driver(
    v2_driver: RobotDriverV2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2: ``cal_begin`` -> снимок -> пять точек роботом v2 -> пять пар мм и энкодер в состоянии мастера, ошибок нет."""
    adapter = _V2HubAdapter(v2_driver)
    monkeypatch.setattr(camera_plugin_module, "DeviceHubClient", lambda _ctx: adapter)
    snaps = _Snapshots()
    ctx = MagicMock()
    ctx.config = {}
    ctx.registers = None
    ctx.state_proxy = snaps
    plugin = CameraRobotCalibrationPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)  # создаёт рабочий поток мастера через ctx.worker_manager.create_worker(name, fn, cfg, ...)
    create_args = ctx.worker_manager.create_worker.call_args
    assert create_args is not None, "start не создал рабочий поток мастера"
    worker_fn = create_args.args[1]

    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=worker_fn, args=(stop, pause), daemon=True, name="t54-calibration-worker")
    worker.start()
    try:
        plugin.cmd_begin({"camera_id": "cam_sim", "robot_id": "robot_main", "vfd_id": "vfd_belt"})
        assert _wait(lambda: snaps.last().get("phase") == "ready", 5.0), f"begin не дошёл: {snaps.last()}"

        plugin.process([{"detections": list(_DETECTIONS)}])
        plugin.cmd_capture_image({})
        assert _wait(lambda: snaps.last().get("captured") is True, 10.0), f"кадр не снят: {snaps.last()}"

        assert v2_driver.call("servo", {"on": True})["status"] == "ok"
        poses: list[tuple[float, float]] = []
        for index, (dx, dy, target) in enumerate(_STEPS):
            step = v2_driver.call("jog_step", {"dx": dx, "dy": dy, "spd": 50})
            assert step["status"] == "ok", f"шаг {index}: {step}"
            poses.append(_wait_pose(v2_driver, target))
            plugin.cmd_set_robot_point({"index": index})
            assert _wait(lambda i=index: snaps.last().get("points_collected") == i + 1, 10.0), (
                f"точка {index} не снята: {snaps.last()}"
            )

        final = snaps.last()
        assert final["error"] is None, final
        assert snaps.errors() == [], snaps.errors()
        assert final["points_collected"] == 5
        assert len(final["mm"]) == 5
        for index, pose in enumerate(poses):
            pair = final["mm"][index]
            assert pair is not None, f"точка {index}: пары мм нет"
            assert pair == pytest.approx(list(pose), abs=_REACH_TOL_MM), f"точка {index}: {pair} против {pose}"
        assert type(final["e0"]) is int, f"энкодер кадра: {final['e0']!r}"
        assert type(final["e1"]) is int, f"энкодер точки: {final['e1']!r}"
        assert adapter.telemetry_calls >= 6, "телеметрия мастера не шла через драйвер v2"
        assert worker.is_alive(), "рабочий поток мастера завис или упал"
    finally:
        stop.set()
        worker.join(timeout=5.0)
    assert not worker.is_alive(), "рабочий поток мастера не завершился по stop_event"


def test_c2_taught_points_are_distinct_poses() -> None:
    """Контроль C2: пять целей отличаются друг от друга (иначе «пять пар мм» совпали бы и вырожденный мастер прошёл)."""
    assert len({target for _dx, _dy, target in _STEPS}) >= 4
    assert max(math.hypot(dx, dy) for dx, dy, _t in _STEPS) <= 20.0 + 1e-9


# --------------------------------------------------------------------------------------------------
# C3 - ключи телеметрии v2 против v1
# --------------------------------------------------------------------------------------------------


def test_c3_v2_telemetry_has_every_key_the_camera_plugin_reads(v2_driver: RobotDriverV2) -> None:
    """C3: ответ v2 несёт ``telemetry`` с ``x_mm``/``y_mm`` и верхний ``encoder`` - всё, что читает ``camera_robot``."""
    res = _telemetry(v2_driver)
    assert {"x_mm", "y_mm"} <= set(res["telemetry"])
    assert "encoder" in res


def test_c3_v2_telemetry_key_set_equals_v1(v2_driver: RobotDriverV2, v1_driver: RobotDriver) -> None:
    """C3: множество ключей ``telemetry`` драйвера v2 равно множеству ключей v1 (сравнение множеств)."""
    v2_keys = set(_telemetry(v2_driver)["telemetry"])
    v1_keys = set(_telemetry(v1_driver)["telemetry"])
    assert v1_keys, "v1 вернул пустую телеметрию: сравнение было бы пустым"
    assert v2_keys == v1_keys, f"только v2: {sorted(v2_keys - v1_keys)}; только v1: {sorted(v1_keys - v2_keys)}"
