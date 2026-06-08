"""Тесты geometry — знаковое расстояние и клиппинг линии к кадру."""

import math

import pytest

from Plugins.filter.line_filter.geometry import (
    signed_distance,
    line_segment_in_frame,
    band_edges_in_frame,
)


class TestSignedDistance:
    def test_on_line_is_zero(self):
        assert signed_distance((320, 240), (320, 240), 0.0) == pytest.approx(0.0)

    def test_angle0_normal_is_vertical(self):
        """angle=0 → нормаль (0,1): расстояние = Δy."""
        assert signed_distance((320, 300), (320, 240), 0.0) == pytest.approx(60.0)
        assert signed_distance((100, 180), (320, 240), 0.0) == pytest.approx(-60.0)

    def test_angle90_normal_is_horizontal(self):
        """angle=90 → нормаль (-1,0): расстояние = -(Δx)."""
        assert signed_distance((400, 240), (320, 240), 90.0) == pytest.approx(-80.0)

    def test_sign_flips_across_line(self):
        a = signed_distance((320, 200), (320, 240), 0.0)
        b = signed_distance((320, 280), (320, 240), 0.0)
        assert a < 0 < b


class TestLineClip:
    @pytest.mark.parametrize("angle", [0, 90, 180, -90, 45, -45, 135])
    def test_returns_segment_for_all_angles(self, angle):
        """Линия через центр кадра пересекает кадр при любом угле."""
        seg = line_segment_in_frame((320, 240), float(angle), 640, 480)
        assert seg is not None
        (ax, ay), (bx, by) = seg
        # Концы внутри кадра (с допуском на float).
        for x, y in (seg[0], seg[1]):
            assert -0.5 <= x <= 640.5
            assert -0.5 <= y <= 480.5
        # Отрезок ненулевой длины.
        assert math.hypot(bx - ax, by - ay) > 1.0

    def test_horizontal_line_angle0(self):
        seg = line_segment_in_frame((320, 240), 0.0, 640, 480)
        (ax, ay), (bx, by) = seg
        assert ay == pytest.approx(240, abs=0.5)
        assert by == pytest.approx(240, abs=0.5)
        assert {round(ax), round(bx)} == {0, 640}

    def test_vertical_line_angle90(self):
        seg = line_segment_in_frame((320, 240), 90.0, 640, 480)
        (ax, ay), (bx, by) = seg
        assert ax == pytest.approx(320, abs=0.5)
        assert bx == pytest.approx(320, abs=0.5)
        assert {round(ay), round(by)} == {0, 480}

    def test_line_outside_frame_returns_none(self):
        """Линия далеко за кадром не пересекает его."""
        seg = line_segment_in_frame((5000, 5000), 0.0, 640, 480)
        assert seg is None


class TestBandEdges:
    def test_two_edges_offset(self):
        """Границы полосы смещены на ±w/2 вдоль нормали."""
        plus, minus = band_edges_in_frame((320, 240), 0.0, 100, 640, 480)
        # angle=0 нормаль (0,1): +50 по y и -50 по y.
        assert plus is not None and minus is not None
        assert plus[0][1] == pytest.approx(290, abs=0.5)
        assert minus[0][1] == pytest.approx(190, abs=0.5)
