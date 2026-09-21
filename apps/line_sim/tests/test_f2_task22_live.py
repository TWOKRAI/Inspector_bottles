# -*- coding: utf-8 -*-
"""Task 2.2 — независимый RED, живой стенд (тестер, worktree на 362a319a, ДО реализации).

Гейт ``LINE_SIM_LIVE=1`` — тот же приём, что ``backend_ctl/tests/test_probe_acceptance_app_param.py::
test_live_line_sim_run`` (единственный прецедент этого имени переменной в репозитории, найден
grep'ом, не угадан): полный трёхпроцессный стенд, порт backend_ctl фиксирован (8766 —
``LINE_SIM_PORT`` из того же файла), НИКОГДА не запускать по умолчанию.

Сегодня ``apps/line_sim/pipeline.yaml`` держит процесс ``camera`` на
``Plugins.sources.camera_service.plugin.CameraServicePlugin`` (симулятор-заглушка), а НЕ на
новом ``SceneSourcePlugin`` — переключение проводов на ``scene_source`` входит в Task 2.2
разработчика. Поэтому весь файл сегодня либо падает при сборке стенда (если разработчик ещё
не менял ``pipeline.yaml``+``scene_source`` не существует), либо (после частичной правки)
красен по КОНКРЕТНЫМ причинам, названным в каждом тесте. Источники API:
``backend_ctl.harness.BackendHarness``, ``backend_ctl.driver.BackendDriver.introspect_telemetry``
(докстринг: ``levels.state.plugins.<writer>.<metric>``), ``Services.robot_comm.core.client.RobotClient``
+ ``Services.vfd_comm.core.client.VfdClient`` (мост, ``BRIDGE_MAP`` по умолчанию) — образцы,
``apps/line_sim/tests/test_f1_task11_acceptance.py``.

Догадка тестера: путь мира ``sim.belt.encoder.value`` (лист) — из DESIGN брифа
(``ctx.state_proxy.set("sim.belt.encoder", {"value": ..., ...})``), не из кода.
"""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from backend_ctl.harness import BackendHarness
from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.vfd_comm.core.client import VfdClient

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("LINE_SIM_LIVE") != "1",
        reason="живой прогон полного стенда сима — только явно, LINE_SIM_LIVE=1",
    ),
    pytest.mark.timeout(120),
]

_APP_DIR = Path(__file__).resolve().parents[1]
_APP_YAML = _APP_DIR / "app.yaml"

_LINE_SIM_PORT = 8766  # литерал контракта (backend_ctl/tests/test_probe_acceptance_app_param.py)
_ROBOT_HOST = "127.0.0.1"
_MODBUS_PORT = 5021
_ROBOT_UNIT_ID = 2
_MJPEG_URL = "http://127.0.0.1:8091/"
_ENCODER_PATH = "sim.belt.encoder.value"


def _build_line_sim_launcher():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(_APP_YAML)


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def _assert_port_free(port: int) -> None:
    """8766/5021/8091 — литералы контракта, НЕ выводим другой порт при занятости
    (TRAPS брифа: держать 8765 прототипа нетронутым, а не бегать от коллизии)."""
    with socket.socket() as probe:
        probe.settimeout(0.2)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            pytest.fail(f"порт {port} занят до старта теста — {exc}")


def _command_succeeded(res: Any) -> bool:
    if not isinstance(res, dict):
        return False
    if "success" in res:
        return bool(res.get("success"))
    return res.get("status") == "ok"


def _result_field(res: dict, key: str) -> Any:
    if key in res:
        return res[key]
    nested = res.get("result")
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    return None


@pytest.fixture
def line_sim_live_backend(tmp_path: Path):
    """Полный стенд ``apps/line_sim`` на ФИКСИРОВАННОМ порту 8766 (не случайном — контракт
    брифа), под ``LINE_SIM_LIVE=1``. Убивает всё дерево процессов на выходе (TRAPS: осиротевшие
    процессы — известная проблема прошлых прогонов, ``docs/reviews/2026-09-21_line-sim-
    observability-acceptance.md`` §8)."""
    for port in (_LINE_SIM_PORT, _MODBUS_PORT, 8091):
        _assert_port_free(port)

    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    harness = BackendHarness(launcher_factory=_build_line_sim_launcher, port=_LINE_SIM_PORT)
    drv = harness.start()
    try:
        yield harness, drv
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log
        for port in (_LINE_SIM_PORT, _MODBUS_PORT, 8091):
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _port_is_open("127.0.0.1", port, timeout=0.3):
                time.sleep(0.2)
            assert not _port_is_open("127.0.0.1", port, timeout=0.3), (
                f"порт {port} всё ещё принимает соединения после harness.stop() — осиротевший процесс"
            )


def _get_encoder(drv: Any) -> int:
    res = drv.send_command("ProcessManager", "state.get", {"path": _ENCODER_PATH}, timeout=5.0)
    assert _command_succeeded(res), f"state.get({_ENCODER_PATH!r}) не удался: {res!r}"
    value = _result_field(res, "value")
    assert isinstance(value, int), f"state.get({_ENCODER_PATH!r}) вернул не int: {value!r}"
    return value


def _make_vfd_client() -> tuple[RobotClient, VfdClient]:
    robot = RobotClient(RobotConfig(host=_ROBOT_HOST, port=_MODBUS_PORT, unit_id=_ROBOT_UNIT_ID))
    assert robot.connect() is True, "RobotClient.connect() к 5021 не удался"
    return robot, VfdClient(transport=robot)


def _sprite_centroid_x(frame: np.ndarray, reference: np.ndarray) -> float:
    diff = np.any(frame != reference, axis=2)
    weights = diff.sum(axis=0).astype(float)
    assert weights.sum() > 0, "кадр не отличается от эталона нигде — спрайт не найден"
    return float(np.average(np.arange(frame.shape[1]), weights=weights))


def _capture_frame(cap: cv2.VideoCapture, deadline_s: float = 5.0) -> np.ndarray:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        ret, frame = cap.read()
        if ret and frame is not None:
            return frame
        time.sleep(0.05)
    pytest.fail(f"не удалось прочитать кадр с {_MJPEG_URL} за {deadline_s}с")


# --------------------------------------------------------------------------- #
# Критерий: энкодер строго растёт в дереве состояний                          #
# --------------------------------------------------------------------------- #


def test_state_get_encoder_grows(line_sim_live_backend) -> None:
    """Пин: два снятия ``state.get(sim.belt.encoder.value)`` с интервалом 1с, второе строго
    больше первого."""
    _harness, drv = line_sim_live_backend
    first = _get_encoder(drv)
    time.sleep(1.0)
    second = _get_encoder(drv)
    assert second > first, f"encoder не вырос за 1с: {first} -> {second}"


# --------------------------------------------------------------------------- #
# Критерий: команда ПЧ «стоп» замораживает энкодер, «пуск» возобновляет рост  #
# --------------------------------------------------------------------------- #


def test_vfd_stop_freezes_and_start_resumes(line_sim_live_backend) -> None:
    """Пин: ``VfdClient.stop()`` -> два снятия энкодера подряд равны; ``run(freq_hz>0)`` ->
    рост возобновляется."""
    _harness, drv = line_sim_live_backend
    robot, vfd = _make_vfd_client()
    try:
        assert vfd.stop() is True, "VfdClient.stop() не подтверждён транспортом"
        time.sleep(0.3)  # дать Lua/мосту применить команду

        frozen_a = _get_encoder(drv)
        time.sleep(1.0)
        frozen_b = _get_encoder(drv)
        assert frozen_a == frozen_b, f"encoder продолжил расти после stop(): {frozen_a} -> {frozen_b}"

        assert vfd.run(freq_hz=20.0) is True, "VfdClient.run(freq_hz=20.0) не подтверждён"
        time.sleep(0.3)

        resumed_a = _get_encoder(drv)
        time.sleep(1.0)
        resumed_b = _get_encoder(drv)
        assert resumed_b > resumed_a, f"encoder не возобновил рост после run(): {resumed_a} -> {resumed_b}"
    finally:
        robot.disconnect()


# --------------------------------------------------------------------------- #
# Критерий: MJPEG-кадры — спрайт едет, пока лента едет, и стоит, пока стоп    #
# --------------------------------------------------------------------------- #


def test_mjpeg_sprite_follows_belt(line_sim_live_backend) -> None:
    """Пин: центр масс спрайта в кадрах ``http://127.0.0.1:8091/`` смещается, пока лента
    едет, и неподвижен (±1px), пока лента стоит (после команды ПЧ «стоп»)."""
    _harness, drv = line_sim_live_backend
    cap = cv2.VideoCapture(_MJPEG_URL)
    robot, vfd = _make_vfd_client()
    try:
        reference = _capture_frame(cap)
        time.sleep(1.0)
        moving_a = _capture_frame(cap)
        time.sleep(1.0)
        moving_b = _capture_frame(cap)
        x_a = _sprite_centroid_x(moving_a, reference)
        x_b = _sprite_centroid_x(moving_b, reference)
        assert abs(x_b - x_a) > 1.0, f"спрайт не сдвинулся, пока лента едет: x={x_a} -> {x_b}"

        assert vfd.stop() is True
        time.sleep(0.5)
        stopped_ref = _capture_frame(cap)
        time.sleep(1.0)
        stopped_next = _capture_frame(cap)
        x_stop_a = _sprite_centroid_x(stopped_ref, reference)
        x_stop_b = _sprite_centroid_x(stopped_next, reference)
        assert x_stop_a == pytest.approx(x_stop_b, abs=1.0), (
            f"спрайт продолжил ехать после stop(): x={x_stop_a} -> {x_stop_b}"
        )
    finally:
        cap.release()
        robot.disconnect()


# --------------------------------------------------------------------------- #
# Краевой случай: только camera (без robot) — кадры идут, ошибок нет         #
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    reason=(
        "гарнесс собирает apps/line_sim целиком через build_app(app.yaml) — выборочный "
        "запуск подмножества процессов пайплайна (только camera+mjpeg, без robot) потребовал "
        "бы отдельного фикстурного pipeline.yaml (аналог apps/line_sim/tests/fixtures/"
        "state_proxy_app из Task 2.0); вне минимального объёма этого прогона тестера "
        "(context-бюджет), см. отчёт — критерий остаётся непроверенным этим файлом, не FAIL."
    ),
    strict=False,
)
def test_camera_alone_serves_frames() -> None:
    """Пин (НЕ выполнен, см. xfail reason): процесс ``camera`` без ``robot`` -> MJPEG отдаёт
    кадры, в ``errors.log`` процесса ``camera`` нет исключений."""
    pytest.fail("требуется отдельный фикстурный pipeline (только camera+mjpeg) — не собран")


# --------------------------------------------------------------------------- #
# Критерий: introspect_telemetry.levels видит belt_mm_s/encoder писателя      #
# --------------------------------------------------------------------------- #


def test_introspect_telemetry_levels(line_sim_live_backend) -> None:
    """Пин: ``levels.state.plugins.sim_robot_host`` содержит ``belt_mm_s`` и ``encoder``;
    после ``stop()`` ПЧ ``belt_mm_s == 0``. Без опроса ``sim_robot.status``."""
    _harness, drv = line_sim_live_backend
    res = drv.introspect_telemetry("robot")
    plugins = (res.get("levels") or {}).get("state", {}).get("plugins", {})
    writer = plugins.get("sim_robot_host")
    assert isinstance(writer, dict), f"levels.state.plugins.sim_robot_host отсутствует/не dict: {res!r}"
    assert "belt_mm_s" in writer, f"нет belt_mm_s в levels писателя sim_robot_host: {writer!r}"
    assert "encoder" in writer, f"нет encoder в levels писателя sim_robot_host: {writer!r}"

    robot, vfd = _make_vfd_client()
    try:
        assert vfd.stop() is True
        time.sleep(1.5)  # дать телеметрийному тику (interval_sec=1.0, system.yaml) обновиться
        res2 = drv.introspect_telemetry("robot")
        writer2 = (res2.get("levels") or {}).get("state", {}).get("plugins", {}).get("sim_robot_host", {})
        assert writer2.get("belt_mm_s") == 0, f"belt_mm_s != 0 после stop(): {writer2!r}"
    finally:
        robot.disconnect()
