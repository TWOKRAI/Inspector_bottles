"""Ф5 — интеграция против НАСТОЯЩЕГО симулятора робота (TCP + реальный RobotDriver).

Цель Ф5 (снять риск без железа): проверить реальный путь телеметрии и потоковую
модель плагина, НЕ мат.точность гомографии.

  1. Контракт телеметрии: реальный RobotDriver.call("get_telemetry") против sim
     возвращает x_mm/y_mm/encoder — ровно то, что читает плагин (_read_telemetry).
  2. Потоковая модель: реальный worker-поток плагина гоняет блокирующие IPC-вызовы
     к драйверу без дедлоков; команды → очередь → worker → публикация прогресса.
  3. Graceful degradation: симулятор НЕ умеет (а) jog оператора к 5 разным точкам,
     (б) физически возить точку лентой — поэтому encoder_scale/compute на sim-данных
     дают ОЖИДАЕМУЮ ошибку (точка не сместилась / вырожденная H), публикуемую в state
     без падения воркера.

Успешный compute+save доказан на синтетике в test_plugin.py
(test_full_wizard_recovers_calibration) — там можно построить согласованные px/mm/enc.

Прогоняется только при установленном pymodbus.
"""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import MagicMock

import pytest

from Services.robot_comm import ROBOT_AVAILABLE

from Plugins.calibration.camera_robot.plugin import CameraRobotCalibrationPlugin

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")

# 5 различных синтетических центров (как будто circle_detector нашёл 5 точек).
_DETECTIONS = [
    {"center": [100.0, 80.0], "radius": 20},
    {"center": [540.0, 90.0], "radius": 20},
    {"center": [560.0, 420.0], "radius": 20},
    {"center": [90.0, 430.0], "radius": 20},
    {"center": [320.0, 250.0], "radius": 20},
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(predicate, timeout: float = 5.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class _FakeStateProxy:
    """Захватывает последний опубликованный snapshot прогресса."""

    def __init__(self) -> None:
        self.last_path: str | None = None
        self.last: dict | None = None

    def set(self, path, data) -> None:
        self.last_path = path
        self.last = data

    def merge(self, path, data) -> None:  # pragma: no cover
        self.set(path, data)


class _SimHubAdapter:
    """Адаптер DeviceHubClient → реальный RobotDriver + sim.

    robot_get_telemetry идёт в НАСТОЯЩИЙ драйвер (контракт телеметрии живой),
    vfd_* — ok-заглушка (мост ПЧ проверяется отдельно в test_sim_e2e).
    """

    def __init__(self, driver) -> None:
        self._driver = driver
        self.calls: list[str] = []

    def request(self, command, args=None, timeout=None):
        self.calls.append(command)
        if command == "robot_get_telemetry":
            return self._driver.call("get_telemetry", args or {})
        if command in ("vfd_run", "vfd_stop", "vfd_set_freq"):
            return {"status": "ok"}
        return {"status": "error", "message": f"unsupported {command}"}


@pytest.fixture(scope="module")
def sim():
    from Services.robot_comm.server.sim_robot import SimRobotServer

    server = SimRobotServer("127.0.0.1", _free_port())
    server.start()
    time.sleep(0.5)
    yield server
    server.stop()


@pytest.fixture
def driver(sim):
    from Services.device_hub.drivers.robot_driver import RobotDriver
    from Services.device_hub.registry.entry import DeviceEntry

    entry = DeviceEntry(
        id="robot_main",
        name="sim",
        kind="robot",
        protocol="delta_universal3",
        transport={"type": "tcp", "host": sim.host, "port": sim.port, "unit_id": 2},
        params={"word_order": "little", "telemetry_interval_s": 0.1},
    )
    drv = RobotDriver(entry, protocol=None)
    assert drv.connect(), "не удалось подключиться к симулятору"
    yield drv
    drv.disconnect()


# --- 1. Контракт телеметрии реального драйвера -----------------------------
def test_real_driver_telemetry_contract(driver):
    res = driver.call("get_telemetry", {})
    assert res["status"] == "ok"
    tel = res["telemetry"]
    assert "x_mm" in tel and "y_mm" in tel, f"нет x_mm/y_mm: {tel.keys()}"
    assert isinstance(res["encoder"], int)
    # Энкодер симулятора растёт — основа belt-компенсации.
    first = res["encoder"]
    assert _wait(lambda: driver.call("get_telemetry", {})["encoder"] > first), "энкодер sim не растёт"


# --- 2. Полный визард через реальный worker-поток (дедлоки/прогресс) --------
def test_wizard_worker_against_sim_no_deadlock(driver):
    plugin = CameraRobotCalibrationPlugin()
    ctx = MagicMock()
    ctx.config = {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    ctx.worker_manager = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    plugin.configure(ctx)
    plugin._client = _SimHubAdapter(driver)
    plugin._last_detections = list(_DETECTIONS)

    # Запустить НАСТОЯЩИЙ worker-поток плагина.
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._calibration_worker, args=(stop, pause), daemon=True)
    worker.start()

    def snap() -> dict:
        return ctx.state_proxy.last or {}

    try:
        plugin.cmd_begin({"camera_id": "cam_sim", "robot_id": "robot_main", "vfd_id": "vfd_belt"})
        assert _wait(lambda: snap().get("phase") == "ready")

        # Снять кадр: detections кэшированы (5 шт) + E0 из РЕАЛЬНОГО энкодера sim.
        plugin.cmd_capture_image({})
        assert _wait(lambda: snap().get("captured") is True), f"кадр не снят: {snap()}"
        assert isinstance(plugin._state["e_capture"], int)

        # 5 точек: mm из реальной телеметрии (sim не двигается → x/y одинаковы, enc растёт).
        for i in range(5):
            plugin.cmd_set_robot_point({"index": i})
            assert _wait(lambda i=i: snap().get("points_collected") == i + 1), f"точка {i} не снята"

        # Лента (vfd-заглушка ok) — без ошибок.
        plugin.cmd_belt_run({"freq": 10.0})
        assert _wait(lambda: "Лента" in (snap().get("message") or ""))
        plugin.cmd_belt_stop({})

        # Масштаб ленты: точка не сместилась (sim) → ОЖИДАЕМАЯ ошибка, воркер жив.
        plugin.cmd_encoder_scale({"ref_index": 0})
        assert _wait(lambda: snap().get("error")), "ожидали ошибку 'точка не сместилась'"
        assert snap().get("scale_done") is False

        # Compute без масштаба → graceful error, не падение.
        plugin.cmd_compute({})
        assert _wait(lambda: snap().get("error"))
        assert plugin._state["homography"] is None

        # Главное Ф5: воркер пережил всю последовательность без дедлока.
        assert worker.is_alive()
        # Телеметрия реально читалась через драйвер.
        assert plugin._client.calls.count("robot_get_telemetry") >= 6
    finally:
        stop.set()
        worker.join(timeout=2.0)

    assert not worker.is_alive(), "worker не завершился по stop_event (дедлок?)"
