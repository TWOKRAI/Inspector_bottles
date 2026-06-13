"""Тесты CameraRobotCalibrationPlugin — визард на синтетике (мок DeviceHubClient).

Тесты гоняют _dispatch напрямую (синхронно, без worker-потока) — так детерминированно
проверяется state-машина. Сценарий движущейся ленты доказывает, что плагин корректно
связывает belt-компенсацию + гомографию end-to-end.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from Plugins.calibration.camera_robot import geometry, plugin as plugin_mod
from Plugins.calibration.camera_robot.plugin import CameraRobotCalibrationPlugin

# --- Синтетическая сцена (та же геометрия, что в test_geometry) ---
PX_CORNERS = [(100.0, 80.0), (540.0, 90.0), (560.0, 420.0), (90.0, 430.0)]  # TL, TR, BR, BL
PX_CENTER = (320.0, 250.0)
PX_ALL = PX_CORNERS + [PX_CENTER]
MM_CORNERS = [(0.0, 0.0), (200.0, 0.0), (200.0, 150.0), (0.0, 150.0)]

E0 = 1000
MPC = 0.05
BD = (0.6, 0.8)
ENC_I = [1100, 1150, 1200, 1080, 1130]
E_B = 1300


class FakeHub:
    """Мок DeviceHubClient: телеметрия отдаётся по очереди, vfd_* → ok."""

    def __init__(self, telemetry: list[tuple[float, float, int]]):
        self._tel = list(telemetry)
        self.calls: list[tuple[str, dict]] = []

    def request(self, command, args=None, timeout=None):
        self.calls.append((command, dict(args or {})))
        if command == "robot_get_telemetry":
            x, y, enc = self._tel.pop(0)
            return {
                "status": "ok",
                "telemetry": {"x_mm": x, "y_mm": y, "z_mm": 0.0, "rz_deg": 0.0},
                "encoder": enc,
                "free": True,
            }
        if command in ("vfd_run", "vfd_stop", "vfd_set_freq"):
            return {"status": "ok"}
        return {"status": "error", "message": f"unknown {command}"}


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.config = {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    ctx.worker_manager = MagicMock()
    ctx.state_proxy = MagicMock()
    return ctx


def _plugin(hub: FakeHub | None = None) -> CameraRobotCalibrationPlugin:
    p = CameraRobotCalibrationPlugin()
    p.configure(_make_ctx())
    if hub is not None:
        p._client = hub
    return p


def _detections(points) -> list[dict]:
    return [{"center": [p[0], p[1]], "radius": 30} for p in points]


def _shift(bf, enc):
    s = (enc - E0) * MPC
    return (bf[0] + s * BD[0], bf[1] + s * BD[1])


def _moving_belt_telemetry():
    """Очередь телеметрии под полный визард: capture, 5 точек, encoder_scale."""
    h_true = geometry.fit_homography(PX_CORNERS, MM_CORNERS)
    belt_fixed = [geometry.apply_homography(h_true, p) for p in PX_ALL]
    mm_measured = [_shift(belt_fixed[i], ENC_I[i]) for i in range(5)]
    r2 = _shift(belt_fixed[0], E_B)
    tel = [(0.0, 0.0, E0)]  # capture → E0
    tel += [(mm_measured[i][0], mm_measured[i][1], ENC_I[i]) for i in range(5)]  # 5 точек
    tel += [(r2[0], r2[1], E_B)]  # encoder_scale ref=0
    return tel


# --- Полный визард (движущаяся лента) -------------------------------------
def test_full_wizard_recovers_calibration(monkeypatch):
    saved = {}

    def _fake_save(cam, payload, **kw):
        saved.update(camera_id=cam, payload=payload)
        return "config/calibration/cam0.yaml"

    monkeypatch.setattr(plugin_mod, "save_calibration", _fake_save)

    hub = FakeHub(_moving_belt_telemetry())
    p = _plugin(hub)
    p._last_detections = _detections(PX_ALL)

    p._dispatch({"action": "begin", "args": {"camera_id": "cam0", "robot_id": "robot_main", "vfd_id": "vfd_belt"}})
    p._dispatch({"action": "capture_image", "args": {}})
    assert p._state["px"] is not None
    assert p._state["e_capture"] == E0
    for i in range(5):
        p._dispatch({"action": "set_robot_point", "args": {"index": i}})
    p._dispatch({"action": "belt_run", "args": {"freq": 10.0}})
    p._dispatch({"action": "encoder_scale", "args": {"ref_index": 0}})
    assert p._state["mm_per_count"] == pytest.approx(MPC, abs=1e-9)
    p._dispatch({"action": "compute", "args": {}})

    assert p._state["error"] is None
    assert p._state["passed"] is True, p._state
    assert p._state["reproj"]["center"] < 1e-3  # belt-компенсация сошлась

    p._dispatch({"action": "save", "args": {}})
    assert saved["camera_id"] == "cam0"
    h = saved["payload"]["px_to_mm"]
    assert len(h) == 3 and len(h[0]) == 3
    assert len(saved["payload"]["points"]) == 5
    # vfd_run был вызван
    assert any(c[0] == "vfd_run" for c in hub.calls)


# --- Ошибка: детектор нашёл ≠5 точек --------------------------------------
def test_capture_wrong_count_errors_no_crash():
    p = _plugin(FakeHub([]))  # телеметрия не понадобится — упадём раньше
    p._last_detections = _detections(PX_ALL[:4])  # только 4
    p._dispatch({"action": "capture_image", "args": {}})
    assert p._state["px"] is None
    assert "вместо 5" in (p._state["error"] or "")


# --- Предусловие: compute до сбора точек -----------------------------------
def test_compute_before_capture_errors():
    p = _plugin(FakeHub([]))
    p._dispatch({"action": "compute", "args": {}})
    assert p._state["homography"] is None
    assert p._state["error"]


# --- Деление на ноль: encoder_scale при том же энкодере ---------------------
def test_encoder_scale_zero_delta_errors():
    # capture(E0), точка0(enc=1100), encoder_scale → телеметрия с тем же enc=1100.
    hub = FakeHub([(0.0, 0.0, E0), (10.0, 20.0, 1100), (99.0, 99.0, 1100)])
    p = _plugin(hub)
    p._last_detections = _detections(PX_ALL)
    p._dispatch({"action": "capture_image", "args": {}})
    p._dispatch({"action": "set_robot_point", "args": {"index": 0}})
    p._dispatch({"action": "encoder_scale", "args": {"ref_index": 0}})
    assert p._state["mm_per_count"] is None
    assert p._state["error"]


# --- Сохранение отклоняется без compute ------------------------------------
def test_save_without_compute_rejected():
    p = _plugin(FakeHub([]))
    p._dispatch({"action": "save", "args": {}})
    assert p._state["saved_path"] is None
    assert p._state["error"]


# --- process() аннотирует кадр, не падает ----------------------------------
def test_process_annotates_frame_no_crash():
    p = _plugin()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = p.process([{"frame": frame, "detections": _detections(PX_ALL)}])
    assert out[0]["frame"].shape == (480, 640, 3)
    # кадр-копия (не тот же объект — мы не мутируем SHM)
    assert out[0]["frame"] is not frame
    # detections закэшированы
    assert len(p._last_detections) == 5
