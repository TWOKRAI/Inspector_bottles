"""Контракт symmetry: авто-детектор и кодирование угла."""

from __future__ import annotations

import math

import pytest

from Services.dataset_gen.core.symmetry import (
    combine_symmetries,
    detect_symmetry,
    encode_angle,
    rotation_difference,
)


class TestRotationDifference:
    def test_identical_at_zero_angle(self, bar_sprite):
        # поворот на 0° — спрайт совпадает сам с собой
        assert rotation_difference(bar_sprite, 0.0) < 0.01

    def test_bar_differs_at_90(self, bar_sprite):
        # брусок 4:1, повёрнутый на 90°, почти не пересекается с оригиналом
        assert rotation_difference(bar_sprite, 90.0) > 0.3

    def test_result_bounded(self, lshape_sprite):
        for angle in (0, 45, 90, 180, 270):
            d = rotation_difference(lshape_sprite, float(angle))
            assert 0.0 <= d <= 1.0


class TestDetectSymmetry:
    def test_disk_is_fully_symmetric(self, disk_sprite):
        assert detect_symmetry(disk_sprite) == "full"

    def test_bar_is_180_symmetric(self, bar_sprite):
        assert detect_symmetry(bar_sprite) == "180"

    def test_lshape_is_asymmetric(self, lshape_sprite):
        assert detect_symmetry(lshape_sprite) == "none"

    def test_rel_threshold_separates_borderline_cases(self, disk_sprite):
        # кейс «буквы П»: П-образный знак на диске почти 180°-симметричен
        # в абсолютной метрике (диск «разбавляет» разность), решает
        # относительный критерий — d180 против типичной разности объекта
        sprite = disk_sprite.copy()
        sprite[24:72, 28:36, :3] = 0  # левая вертикаль
        sprite[24:72, 60:68, :3] = 0  # правая вертикаль
        sprite[24:32, 28:68, :3] = 0  # верхняя перекладина (несимметричная деталь)
        assert detect_symmetry(sprite, rel_threshold=0.05) == "none"
        assert detect_symmetry(sprite, rel_threshold=1.0) == "180"


class TestCombineSymmetries:
    def test_any_none_wins(self):
        assert combine_symmetries({"full", "none"}) == "none"

    def test_180_beats_full(self):
        assert combine_symmetries({"full", "180"}) == "180"

    def test_all_full_stays_full(self):
        assert combine_symmetries({"full"}) == "full"


class TestEncodeAngle:
    def test_none_encodes_raw_angle(self):
        # given класс без симметрии, when кодируем 30°
        sin_v, cos_v, valid = encode_angle(30.0, "none")
        # then обычные sin/cos и валидный флаг
        assert valid is True
        assert sin_v == pytest.approx(math.sin(math.radians(30)))
        assert cos_v == pytest.approx(math.cos(math.radians(30)))

    def test_unit_norm_when_valid(self):
        for sym in ("none", "180"):
            sin_v, cos_v, valid = encode_angle(137.0, sym)
            assert valid
            assert sin_v**2 + cos_v**2 == pytest.approx(1.0)

    def test_180_makes_theta_and_theta_plus_180_identical(self):
        # ключевое свойство: для 180°-симметрии θ и θ+180° неразличимы
        a = encode_angle(73.0, "180")
        b = encode_angle(253.0, "180")
        assert a[0] == pytest.approx(b[0], abs=1e-9)
        assert a[1] == pytest.approx(b[1], abs=1e-9)

    def test_full_symmetry_invalidates_angle(self):
        sin_v, cos_v, valid = encode_angle(211.0, "full")
        assert (sin_v, cos_v, valid) == (0.0, 0.0, False)
