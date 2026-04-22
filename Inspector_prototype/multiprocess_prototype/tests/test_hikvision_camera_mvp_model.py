# multiprocess_prototype/tests/test_hikvision_camera_mvp_model.py
"""Юнит-тесты HikvisionCameraMvpModel (регистры, clamp, диапазон)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_proto = Path(__file__).resolve().parent.parent
_root = _proto.parent
for _p in (
    str(_root),
    str(_root / "multiprocess_framework" / "refactored" / "modules"),
    str(_root / "multiprocess_framework" / "modules"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multiprocess_prototype.registers.schemas.camera_tab import (
    CAMERA_REGISTER,
    HIKVISION_SET_PARAMETER_REGISTER_FIELDS,
    build_hikvision_param_rows,
)

from multiprocess_prototype.frontend.widgets.hikvision_camera_mvp.model import (
    HikvisionCameraMvpModel,
)
from multiprocess_prototype.frontend.widgets.hikvision_camera_mvp.schemas import (
    HikvisionCameraMvpUiConfig,
)


@dataclass
class _FakeReg:
    hikvision_frame_rate: float = 30.0
    hikvision_exposure_time: float = 5000.0
    hikvision_gain: float = 1.0


@dataclass
class _FakeRm:
    _reg: Any = field(default_factory=_FakeReg)
    sets: list = field(default_factory=list)

    def get_register(self, name: str):
        if name == CAMERA_REGISTER:
            return self._reg
        return None

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> None:
        self.sets.append((register_name, field_name, value))
        setattr(self._reg, field_name, value)


def _model(rm):
    return HikvisionCameraMvpModel(rm=rm, ui=HikvisionCameraMvpUiConfig())


def test_read_params_from_register_order():
    rm = _FakeRm()
    m = _model(rm)
    assert m.read_params_from_register() == (30.0, 5000.0, 1.0)


def test_clamp_parameters():
    m = HikvisionCameraMvpModel(rm=None, ui=HikvisionCameraMvpUiConfig())
    out = m.clamp_parameters((0.0, 2_000_000.0, 100.0))
    assert out[0] == 1.0  # min hikvision_frame_rate from CameraRegisters
    assert out[1] == 100_000.0  # hikvision_exposure_time max
    assert out[2] == 24.0  # hikvision_gain max


def test_parameters_out_of_range_detects():
    m = HikvisionCameraMvpModel(rm=None, ui=HikvisionCameraMvpUiConfig())
    issues = m.parameters_out_of_range((0.0, 5000.0, 0.0))
    assert any("frame_rate" in s for s in issues)


def test_build_hikvision_param_rows_order_and_api_keys():
    rows = build_hikvision_param_rows()
    assert len(rows) == len(HIKVISION_SET_PARAMETER_REGISTER_FIELDS)
    for i, fname in enumerate(HIKVISION_SET_PARAMETER_REGISTER_FIELDS):
        assert rows[i].register_field == fname
        assert rows[i].api_key in ("frame_rate", "exposure_time", "gain")


def test_apply_params_to_register_by_api_key():
    rm = _FakeRm()
    m = _model(rm)
    m.apply_params_to_register(
        {"frame_rate": 10.0, "exposure_time": 8000.0, "gain": 2.5}
    )
    assert rm._reg.hikvision_frame_rate == 10.0
    assert rm._reg.hikvision_exposure_time == 8000.0
    assert rm._reg.hikvision_gain == 2.5
