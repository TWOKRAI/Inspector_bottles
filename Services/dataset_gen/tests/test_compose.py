"""Контракт compose: поворот с expand, обрезка по альфе, композиция."""

from __future__ import annotations

import numpy as np
import pytest

from Services.dataset_gen.core.compose import (
    cast_contact_shadow,
    composite,
    crop_to_alpha,
    fit_longest_side,
    rotate_expand,
)


class TestRotateExpand:
    def test_90_degrees_swaps_proportions(self, bar_sprite):
        # given горизонтальный брусок, when поворот на 90° с expand
        cropped = crop_to_alpha(rotate_expand(bar_sprite, 90.0))
        # then объект стал вертикальным (высота > ширины)
        assert cropped.shape[0] > cropped.shape[1] * 2

    def test_added_canvas_is_transparent(self, bar_sprite):
        rotated = rotate_expand(bar_sprite, 45.0)
        # углы расширенного холста полностью прозрачны
        assert rotated[0, 0, 3] == 0
        assert rotated[-1, -1, 3] == 0

    def test_content_not_clipped(self, bar_sprite):
        # площадь непрозрачного сохраняется при повороте (±интерполяция)
        area_before = int((bar_sprite[:, :, 3] > 127).sum())
        rotated = rotate_expand(bar_sprite, 30.0)
        area_after = int((rotated[:, :, 3] > 127).sum())
        assert area_after == pytest.approx(area_before, rel=0.05)


class TestCropToAlpha:
    def test_bbox_is_tight(self, disk_sprite):
        cropped = crop_to_alpha(disk_sprite)
        # все четыре края содержат непрозрачные пиксели
        assert cropped[0, :, 3].max() > 0
        assert cropped[-1, :, 3].max() > 0
        assert cropped[:, 0, 3].max() > 0
        assert cropped[:, -1, 3].max() > 0

    def test_fully_transparent_sprite_rejected(self):
        with pytest.raises(ValueError):
            crop_to_alpha(np.zeros((10, 10, 4), dtype=np.uint8))


class TestFitLongestSide:
    def test_longest_side_hits_target(self, bar_sprite):
        cropped = crop_to_alpha(bar_sprite)
        resized = fit_longest_side(cropped, 50)
        assert max(resized.shape[:2]) == 50

    def test_aspect_ratio_preserved(self, bar_sprite):
        cropped = crop_to_alpha(bar_sprite)
        ratio_before = cropped.shape[1] / cropped.shape[0]
        resized = fit_longest_side(cropped, 60)
        ratio_after = resized.shape[1] / resized.shape[0]
        assert ratio_after == pytest.approx(ratio_before, rel=0.15)


class TestComposite:
    def test_object_center_shows_sprite_color(self, disk_sprite):
        bg = np.full((100, 100, 3), 10, dtype=np.uint8)
        out = composite(bg, disk_sprite, (50.0, 50.0))
        # центр — белый диск, угол — нетронутый фон
        assert out[50, 50].min() > 200
        assert (out[0, 0] == 10).all()

    def test_background_not_mutated(self, disk_sprite):
        bg = np.full((100, 100, 3), 10, dtype=np.uint8)
        composite(bg, disk_sprite, (50.0, 50.0))
        assert (bg == 10).all()

    def test_offscreen_sprite_is_safe(self, disk_sprite):
        bg = np.full((100, 100, 3), 10, dtype=np.uint8)
        out = composite(bg, disk_sprite, (-500.0, -500.0))
        assert (out == bg).all()

    def test_partial_overlap_clips_without_error(self, disk_sprite):
        bg = np.full((100, 100, 3), 10, dtype=np.uint8)
        out = composite(bg, disk_sprite, (0.0, 0.0))
        assert out.shape == bg.shape


class TestContactShadow:
    def test_darkens_region_under_object(self, disk_sprite):
        bg = np.full((120, 120, 3), 200, dtype=np.uint8)
        out = cast_contact_shadow(bg, disk_sprite, (60.0, 60.0), opacity=0.5, blur_px=5, offset_xy=(4, 4))
        # под объектом фон затемнён, дальний угол — нет
        assert out[60, 60].mean() < 180
        assert out[0, 0].mean() == pytest.approx(200, abs=1)

    def test_background_copy_not_mutated(self, disk_sprite):
        bg = np.full((120, 120, 3), 200, dtype=np.uint8)
        cast_contact_shadow(bg, disk_sprite, (60.0, 60.0), 0.5, 5, (0, 0))
        assert (bg == 200).all()

    def test_offscreen_object_is_safe(self, disk_sprite):
        bg = np.full((120, 120, 3), 200, dtype=np.uint8)
        out = cast_contact_shadow(bg, disk_sprite, (-500.0, -500.0), 0.5, 5, (0, 0))
        assert (out == bg).all()
