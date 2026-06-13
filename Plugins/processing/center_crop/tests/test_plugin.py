"""Тесты CenterCropPlugin: configure, crop, границы (clamp/pad/drop), fan-out, sidecar."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from Plugins.processing.center_crop.plugin import CenterCropPlugin


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _plugin(config: dict | None = None) -> CenterCropPlugin:
    p = CenterCropPlugin()
    p.configure(_make_mock_ctx(config))
    return p


def _frame(h: int = 400, w: int = 400) -> np.ndarray:
    """BGR-кадр с градиентом по координате — чтобы проверять, ЧТО вырезано."""
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[..., 0] = (np.arange(w) % 256).astype(np.uint8)[None, :]  # B зависит от x
    f[..., 1] = (np.arange(h) % 256).astype(np.uint8)[:, None]  # G зависит от y
    return f


def _item(frame, filtered, detections=None, **extra) -> dict:
    it = {"frame": frame, "filtered": filtered}
    if detections is not None:
        it["detections"] = detections
    it.update(extra)
    return it


class TestConfigure:
    def test_defaults(self):
        p = _plugin()
        assert p._reg.side_px == 200
        assert p._reg.pad_if_oob is True
        assert p._reg.drop_partial is False

    def test_overrides(self):
        p = _plugin({"side_px": 64, "drop_partial": True, "pad_if_oob": False})
        assert p._reg.side_px == 64
        assert p._reg.drop_partial is True
        assert p._reg.pad_if_oob is False


class TestProcessBasics:
    def test_no_frame(self):
        p = _plugin()
        assert p.process([{"filtered": [{"xy": [10, 10]}]}]) == []

    def test_empty_filtered(self):
        p = _plugin()
        assert p.process([_item(_frame(), [])]) == []

    def test_no_filtered_key(self):
        p = _plugin()
        assert p.process([{"frame": _frame()}]) == []

    def test_fully_inside_exact_size(self):
        p = _plugin({"side_px": 200})
        out = p.process([_item(_frame(400, 400), [{"xy": [200, 200]}])])
        assert len(out) == 1
        crop = out[0]["frame"]
        assert crop.shape == (200, 200, 3)
        # центр выреза должен совпасть с пикселем (200,200) исходника
        src = _frame(400, 400)
        assert int(crop[100, 100, 0]) == int(src[200, 200, 0])

    def test_fan_out_multiple_centers(self):
        p = _plugin({"side_px": 100})
        out = p.process([_item(_frame(400, 400), [{"xy": [150, 150]}, {"xy": [250, 250]}])])
        assert len(out) == 2
        assert out[0]["crop_index"] == 0
        assert out[1]["crop_index"] == 1
        assert all(o["frame"].shape == (100, 100, 3) for o in out)


class TestBoundary:
    def test_drop_partial(self):
        p = _plugin({"side_px": 200, "drop_partial": True})
        out = p.process([_item(_frame(400, 400), [{"xy": [10, 10]}])])
        assert out == []  # вырез вышел за границу → пропущен

    def test_drop_partial_priority_over_pad(self):
        p = _plugin({"side_px": 200, "drop_partial": True, "pad_if_oob": True})
        out = p.process([_item(_frame(400, 400), [{"xy": [10, 10]}])])
        assert out == []

    def test_pad_if_oob_keeps_full_size(self):
        p = _plugin({"side_px": 200, "drop_partial": False, "pad_if_oob": True, "pad_color_bgr": [0, 0, 0]})
        out = p.process([_item(_frame(400, 400), [{"xy": [10, 10]}])])
        assert len(out) == 1
        assert out[0]["frame"].shape == (200, 200, 3)
        # верхний-левый угол выреза (вне кадра) должен быть pad (0)
        assert int(out[0]["frame"][0, 0, 0]) == 0

    def test_clamp_smaller_than_side(self):
        p = _plugin({"side_px": 200, "drop_partial": False, "pad_if_oob": False})
        out = p.process([_item(_frame(400, 400), [{"xy": [10, 10]}])])
        assert len(out) == 1
        # центр (10,10), half=100 → окно [-90..110] обрезано к [0..110] = 110×110
        assert out[0]["frame"].shape == (110, 110, 3)

    def test_center_fully_outside_clamp_skipped(self):
        p = _plugin({"side_px": 50, "drop_partial": False, "pad_if_oob": False})
        out = p.process([_item(_frame(400, 400), [{"xy": [1000, 1000]}])])
        assert out == []


class TestSidecar:
    def test_sidecar_basic_fields(self):
        p = _plugin({"side_px": 100})
        out = p.process(
            [_item(_frame(400, 400), [{"xy": [200, 200], "id": 7}], seq_id=42, camera_id=0, frame_id=5, timestamp=1.5)]
        )
        sc = out[0]["sidecar"]
        assert sc["center_px"] == [200, 200]
        assert sc["side_px"] == 100
        assert sc["track_id"] == 7
        assert sc["seq_id"] == 42
        assert sc["camera_id"] == 0
        assert sc["frame_id"] == 5
        assert sc["timestamp"] == 1.5
        # корреляционные ключи дублируются и на верхнем уровне item (для роутинга/Join)
        assert out[0]["seq_id"] == 42

    def test_radius_matched_from_detections(self):
        p = _plugin({"side_px": 100, "radius_match_dist": 30})
        out = p.process(
            [_item(_frame(400, 400), [{"xy": [200, 200]}], detections=[{"center": [205, 198], "radius": 44}])]
        )
        assert out[0]["sidecar"]["radius_px"] == 44

    def test_radius_none_when_too_far(self):
        p = _plugin({"side_px": 100, "radius_match_dist": 10})
        out = p.process(
            [_item(_frame(400, 400), [{"xy": [200, 200]}], detections=[{"center": [300, 300], "radius": 44}])]
        )
        assert out[0]["sidecar"]["radius_px"] is None

    def test_radius_none_when_match_disabled(self):
        p = _plugin({"side_px": 100, "radius_match_dist": 0})
        out = p.process(
            [_item(_frame(400, 400), [{"xy": [200, 200]}], detections=[{"center": [200, 200], "radius": 44}])]
        )
        assert out[0]["sidecar"]["radius_px"] is None


class TestSizeModeRadius:
    """size_mode=radius — сторона выреза под размер круга (2·r·scale + 2·margin)."""

    def test_side_from_radius(self):
        # radius=40, scale=1.0, margin=10 → side = 2·40 + 2·10 = 100
        p = _plugin({"size_mode": "radius", "radius_scale": 1.0, "margin_px": 10})
        det = [{"center": [200, 200], "radius": 40}]
        out = p.process([_item(_frame(400, 400), [{"xy": [200, 200], "id": 1}], detections=det)])
        assert len(out) == 1
        crop = out[0]["frame"]
        assert crop.shape[0] == 100 and crop.shape[1] == 100
        assert out[0]["sidecar"]["size_mode"] == "radius"
        assert out[0]["sidecar"]["side_px"] == 100  # фактическая сторона
        assert out[0]["sidecar"]["radius_px"] == 40

    def test_radius_scale_and_margin(self):
        # radius=30, scale=1.5, margin=5 → round(2·30·1.5) + 2·5 = 90 + 10 = 100
        p = _plugin({"size_mode": "radius", "radius_scale": 1.5, "margin_px": 5})
        det = [{"center": [200, 200], "radius": 30}]
        out = p.process([_item(_frame(400, 400), [{"xy": [200, 200]}], detections=det)])
        assert out[0]["frame"].shape[0] == 100

    def test_fallback_to_side_px_when_no_radius(self):
        # size_mode=radius, но круг не сопоставлен (нет detections) → fallback side_px
        p = _plugin({"size_mode": "radius", "side_px": 64})
        out = p.process([_item(_frame(400, 400), [{"xy": [200, 200]}], detections=[])])
        assert out[0]["frame"].shape[0] == 64
        assert out[0]["sidecar"]["side_px"] == 64

    def test_fixed_mode_ignores_radius(self):
        # size_mode=fixed (дефолт) → строго side_px, радиус не влияет на размер
        p = _plugin({"size_mode": "fixed", "side_px": 80})
        det = [{"center": [200, 200], "radius": 40}]
        out = p.process([_item(_frame(400, 400), [{"xy": [200, 200]}], detections=det)])
        assert out[0]["frame"].shape[0] == 80
        assert out[0]["sidecar"]["size_mode"] == "fixed"


class TestOutputSize:
    """output_size — ресайз выреза к единому размеру (для ML-датасета)."""

    def test_resize_radius_crop_to_uniform(self):
        # size_mode=radius даёт side=100, но output_size=224 → ресайз к 224×224
        p = _plugin({"size_mode": "radius", "radius_scale": 1.0, "margin_px": 10, "output_size": 224})
        det = [{"center": [200, 200], "radius": 40}]
        out = p.process([_item(_frame(400, 400), [{"xy": [200, 200]}], detections=det)])
        crop = out[0]["frame"]
        assert crop.shape[0] == 224 and crop.shape[1] == 224
        assert out[0]["sidecar"]["side_px"] == 100  # геометрия сохранена
        assert out[0]["sidecar"]["output_size"] == 224
        assert out[0]["sidecar"]["crop_h"] == 224  # фактический размер после ресайза

    def test_output_size_zero_keeps_native(self):
        p = _plugin({"size_mode": "fixed", "side_px": 80, "output_size": 0})
        out = p.process([_item(_frame(400, 400), [{"xy": [200, 200]}])])
        assert out[0]["frame"].shape[0] == 80
        assert out[0]["sidecar"]["output_size"] == 0

    def test_uniform_size_across_different_radii(self):
        # Два круга разного радиуса → оба выреза приводятся к одному output_size
        p = _plugin({"size_mode": "radius", "output_size": 128, "radius_match_dist": 30})
        det = [{"center": [100, 100], "radius": 30}, {"center": [300, 300], "radius": 60}]
        filtered = [{"xy": [100, 100]}, {"xy": [300, 300]}]
        out = p.process([_item(_frame(400, 400), filtered, detections=det)])
        assert len(out) == 2
        assert all(o["frame"].shape[:2] == (128, 128) for o in out)


class TestCommands:
    def test_set_side(self):
        p = _plugin()
        res = p.set_side({"side_px": 128})
        assert res["status"] == "ok"
        assert p._reg.side_px == 128
