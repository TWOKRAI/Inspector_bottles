"""Тесты store.py — хранилище калибровки config/calibration/<camera_id>.yaml."""

from __future__ import annotations

import numpy as np
import pytest

from Plugins.calibration.camera_robot.store import (
    calibration_path,
    load_calibration,
    save_calibration,
    validate_payload,
)


def _valid_payload(camera_id: str = "cam0") -> dict:
    return {
        "camera_id": camera_id,
        "robot_id": "robot_main",
        "created_utc": "2026-06-13T10:00:00Z",
        "transform": "homography",
        "px_to_mm": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "encoder": {"e_capture": 1000, "mm_per_count": 0.05, "belt_dir_mm": [1.0, 0.0]},
        "reproj_error_mm": {"center": 0.42, "mean": 0.31, "max": 0.55},
        "points": [
            {"px": [100, 80], "mm": [0.0, 0.0], "enc": 1100, "role": "corner_tl"},
            {"px": [320, 250], "mm": [100.0, 75.0], "enc": 1130, "role": "center"},
        ],
    }


def test_calibration_path_uses_camera_id(tmp_path):
    p = calibration_path("cam7", base_dir=tmp_path)
    assert p == tmp_path / "cam7.yaml"


def test_calibration_path_empty_id_raises():
    with pytest.raises(ValueError):
        calibration_path("   ")


def test_save_then_load_roundtrip(tmp_path):
    payload = _valid_payload()
    path = save_calibration("cam0", payload, base_dir=tmp_path)
    assert path.exists()
    loaded = load_calibration("cam0", base_dir=tmp_path)
    assert loaded is not None
    assert loaded["camera_id"] == "cam0"
    assert loaded["px_to_mm"] == payload["px_to_mm"]
    assert loaded["encoder"]["mm_per_count"] == 0.05
    assert loaded["reproj_error_mm"]["center"] == 0.42


def test_load_missing_file_returns_none(tmp_path):
    assert load_calibration("nope", base_dir=tmp_path) is None


def test_save_converts_numpy_types(tmp_path):
    payload = _valid_payload()
    h = np.eye(3, dtype=np.float64)
    h[0, 2] = np.float64(12.5)
    payload["px_to_mm"] = h  # numpy-матрица напрямую
    payload["encoder"]["e_capture"] = np.int64(1000)
    payload["encoder"]["belt_dir_mm"] = np.array([0.6, 0.8])
    save_calibration("cam0", payload, base_dir=tmp_path)
    loaded = load_calibration("cam0", base_dir=tmp_path)
    assert loaded["px_to_mm"][0][2] == 12.5
    assert loaded["encoder"]["e_capture"] == 1000
    assert loaded["encoder"]["belt_dir_mm"] == [0.6, 0.8]


def test_overwrite_existing(tmp_path):
    save_calibration("cam0", _valid_payload(), base_dir=tmp_path)
    payload2 = _valid_payload()
    payload2["robot_id"] = "robot_2"
    save_calibration("cam0", payload2, base_dir=tmp_path)
    loaded = load_calibration("cam0", base_dir=tmp_path)
    assert loaded["robot_id"] == "robot_2"


def test_validate_payload_ok():
    assert validate_payload(_valid_payload()) == []


def test_validate_payload_catches_missing_fields():
    bad = _valid_payload()
    del bad["robot_id"]
    del bad["encoder"]
    problems = validate_payload(bad)
    assert any("robot_id" in p for p in problems)
    assert any("encoder" in p for p in problems)


def test_validate_payload_catches_bad_homography():
    bad = _valid_payload()
    bad["px_to_mm"] = [[1.0, 0.0], [0.0, 1.0]]  # 2×2, не 3×3
    problems = validate_payload(bad)
    assert any("px_to_mm" in p for p in problems)


def test_save_rejects_malformed(tmp_path):
    bad = _valid_payload()
    del bad["px_to_mm"]
    with pytest.raises(ValueError):
        save_calibration("cam0", bad, base_dir=tmp_path)
