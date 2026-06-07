"""Тесты control-core вебкамеры (webcam_controls) через fake-cap.

FakeCap имитирует cv2.VideoCapture: хранит свойства в dict, .set/.get работают
с ними. Это позволяет проверить маппинг/clamp/MJPG/порядок без железа.
"""

from __future__ import annotations

import cv2

from Plugins.sources.camera_service.backends import webcam_controls as wc


class FakeCap:
    """Минимальный фейк cv2.VideoCapture для тестов set/get."""

    def __init__(self) -> None:
        self.props: dict[int, float] = {}
        self.set_order: list[int] = []

    def set(self, prop: int, value: float) -> bool:
        self.props[prop] = float(value)
        self.set_order.append(prop)
        return True

    def get(self, prop: int) -> float:
        return self.props.get(prop, 0.0)


# --- apply_param ---


class TestApplyParam:
    def test_int_param_set(self):
        cap = FakeCap()
        assert wc.apply_param(cap, "gain", 100) is True
        assert cap.props[cv2.CAP_PROP_GAIN] == 100.0

    def test_clamp_to_max(self):
        cap = FakeCap()
        wc.apply_param(cap, "gain", 9999)  # max=255
        assert cap.props[cv2.CAP_PROP_GAIN] == 255.0

    def test_clamp_to_min(self):
        cap = FakeCap()
        wc.apply_param(cap, "exposure", -999)  # min=-13
        assert cap.props[cv2.CAP_PROP_EXPOSURE] == -13.0

    def test_bool_param_on_off_mapping(self):
        cap = FakeCap()
        wc.apply_param(cap, "auto_exposure", True)
        assert cap.props[cv2.CAP_PROP_AUTO_EXPOSURE] == 0.75
        wc.apply_param(cap, "auto_exposure", False)
        assert cap.props[cv2.CAP_PROP_AUTO_EXPOSURE] == 0.25

    def test_unknown_param_returns_false(self):
        cap = FakeCap()
        assert wc.apply_param(cap, "does_not_exist", 1) is False

    def test_none_cap_returns_false(self):
        assert wc.apply_param(None, "gain", 1) is False


# --- MJPG ---


class TestMjpg:
    def test_set_mjpg_on_sets_fourcc(self):
        cap = FakeCap()
        assert wc.set_mjpg(cap, True) is True
        expected = cv2.VideoWriter_fourcc(*"MJPG")
        assert cap.props[cv2.CAP_PROP_FOURCC] == float(expected)

    def test_set_mjpg_off_sets_yuy2(self):
        cap = FakeCap()
        wc.set_mjpg(cap, False)
        expected = cv2.VideoWriter_fourcc(*"YUY2")
        assert cap.props[cv2.CAP_PROP_FOURCC] == float(expected)

    def test_none_cap(self):
        assert wc.set_mjpg(None, True) is False


# --- apply_open_sequence: порядок ---


class TestOpenSequence:
    def test_mjpg_set_before_resolution(self):
        cap = FakeCap()
        wc.apply_open_sequence(cap, mjpg=True, width=1280, height=720, fps=30)
        idx_fourcc = cap.set_order.index(cv2.CAP_PROP_FOURCC)
        idx_w = cap.set_order.index(cv2.CAP_PROP_FRAME_WIDTH)
        idx_h = cap.set_order.index(cv2.CAP_PROP_FRAME_HEIGHT)
        assert idx_fourcc < idx_w < idx_h

    def test_no_mjpg_skips_fourcc(self):
        cap = FakeCap()
        wc.apply_open_sequence(cap, mjpg=False, width=640, height=480)
        assert cv2.CAP_PROP_FOURCC not in cap.props

    def test_params_applied(self):
        cap = FakeCap()
        wc.apply_open_sequence(cap, width=640, height=480, params={"gain": 50})
        assert cap.props[cv2.CAP_PROP_GAIN] == 50.0


# --- read_actual + decode_fourcc ---


class TestReadActual:
    def test_decode_fourcc(self):
        code = cv2.VideoWriter_fourcc(*"MJPG")
        assert wc.decode_fourcc(code) == "MJPG"

    def test_read_actual_base_and_fourcc(self):
        cap = FakeCap()
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        actual = wc.read_actual(cap)
        assert actual["width"] == 1280
        assert actual["height"] == 720
        assert actual["fps"] == 30
        assert actual["fourcc"] == "MJPG"

    def test_read_actual_subset(self):
        cap = FakeCap()
        cap.set(cv2.CAP_PROP_GAIN, 77)
        actual = wc.read_actual(cap, names=["gain"])
        assert actual == {"gain": 77.0}

    def test_none_cap_returns_empty(self):
        assert wc.read_actual(None) == {}
