# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.2 (`--gap-alpha`): что может сломаться в ЭТОМ механизме, как он устроен.

Слепые приёмочные тесты — в `test_acceptance_layer_render_1_2_gap_alpha.py`; здесь только то, что видно
автору: порядок «масштаб -> шов -> маска», срез бортов по `-0`, включительные границы, чистота функции,
побайтная неизменность пути без флага.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode
from Services.line_sim.tools import make_seamless_texture as tool

_P = 40
_H = 96


def _photo() -> np.ndarray:
    """BGR (96, 400, 3): мята + серые звенья через период 40, детерминированный шум — период находится."""
    img = np.zeros((_H, _P * 10, 3), np.int32)
    img[:] = (130, 160, 120)
    for k in range(10):
        img[22:74, k * _P + 4 : k * _P + 32] = (90, 80, 78)
    y, x, c = np.mgrid[0:_H, 0 : _P * 10, 0:3]
    return np.clip(img + ((x * 7 + y * 13 + c * 3) % 5 - 2), 0, 255).astype(np.uint8)


def _write_photo(tmp_path: Path) -> Path:
    src = tmp_path / "photo.png"
    imwrite_unicode(str(src), _photo())
    return src


def test_mask_is_computed_on_final_tile_after_scale_and_seam(tmp_path, monkeypatch):
    """Вход `gap_alpha_mask` == RGB записанного тайла побайтно (масштаб 0.5 + шов уже применены), а не
    исходное фото: форма и содержимое другие. Шпион передаёт вызов дальше — проверяется ВХОД, не имя."""
    seen: list[np.ndarray] = []
    real = tool.gap_alpha_mask

    def spy(tile_rgb, **kw):
        seen.append(tile_rgb.copy())
        return real(tile_rgb, **kw)

    monkeypatch.setattr(tool, "gap_alpha_mask", spy)
    src, out = _write_photo(tmp_path), tmp_path / "t.png"
    rc = tool.main([str(src), "--out", str(out), "--scene-px-per-mm", "0.5", "--photo-width-mm", "400", "--gap-alpha"])
    assert rc == 0 and len(seen) == 1
    shipped = imread_unicode(str(out), cv2.IMREAD_UNCHANGED)
    assert shipped.shape[2] == 4
    shipped_rgb = cv2.cvtColor(np.ascontiguousarray(shipped[:, :, :3]), cv2.COLOR_BGR2RGB)
    assert np.array_equal(seen[0], shipped_rgb), "маска посчитана не по записанному тайлу"
    photo_shape = _photo().shape
    assert seen[0].shape != photo_shape, f"маска посчитана по исходному фото {photo_shape}"
    assert np.array_equal(shipped[:, :, 3], real(seen[0])), "альфа в файле != маска по тайлу с дефолтными порогами"


def test_rails_rows_always_opaque_even_on_all_gap_image():
    """Целиком «просветная» картинка: строки [0, TOP) и [h-BOTTOM, h) — 255, середина — 0."""
    mint = cv2.cvtColor(np.full((20, 7, 3), (70, 150, 150), np.uint8), cv2.COLOR_HSV2RGB)
    mask = tool.gap_alpha_mask(mint, hue=(60, 80), sat_min=100, rails_px=(3, 5))
    assert (mask[:3] == 255).all() and (mask[-5:] == 255).all()
    assert (mask[3:15] == 0).all(), "вне бортов всё — просвет"


def test_rails_zero_bottom_does_not_clear_everything():
    """BOTTOM=0: срез `gap[-0:]` стёр бы весь массив (-0 == 0). Борт снизу отсутствует — прозрачны ВСЕ строки."""
    mint = cv2.cvtColor(np.full((10, 4, 3), (70, 150, 150), np.uint8), cv2.COLOR_HSV2RGB)
    assert (tool.gap_alpha_mask(mint, hue=(60, 80), sat_min=100, rails_px=(0, 0)) == 0).all()
    top_only = tool.gap_alpha_mask(mint, hue=(60, 80), sat_min=100, rails_px=(2, 0))
    assert (top_only[:2] == 255).all() and (top_only[2:] == 0).all()


def test_no_flag_output_is_byte_identical_to_pre_task_write_path(tmp_path):
    """Без `--gap-alpha`: файл побайтно равен записи `imwrite_unicode(tile)` напрямую (путь до задачи),
    независимо от версии zlib (эталон строится тут же, а не снят литералом)."""
    src, out = _write_photo(tmp_path), tmp_path / "plain.png"
    assert tool.main([str(src), "--out", str(out)]) == 0
    reference = tmp_path / "ref.png"
    imwrite_unicode(str(reference), tool.make_seamless_tile(_photo()).tile)
    assert out.read_bytes() == reference.read_bytes()


@pytest.mark.parametrize("channel", ["hue", "sat"])
def test_threshold_bounds_are_inclusive_at_both_edges(channel):
    """Пиксель с известным HSV (после круговой конверсии): граница == значению -> просвет, на 1 мимо -> нет."""
    rgb = cv2.cvtColor(np.uint8([[(70, 150, 150)]]), cv2.COLOR_HSV2RGB)
    h, s, _ = (int(v) for v in cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[0, 0])

    def zero(hue=(0, 179), sat_min=0) -> bool:
        return int(tool.gap_alpha_mask(rgb, hue=hue, sat_min=sat_min, rails_px=(0, 0))[0, 0]) == 0

    if channel == "hue":
        assert zero(hue=(h, h)) and zero(hue=(h, 179)) and zero(hue=(0, h))
        assert not zero(hue=(h + 1, 179)) and not zero(hue=(0, h - 1))
    else:
        assert zero(sat_min=s) and not zero(sat_min=s + 1)


def test_gap_alpha_mask_does_not_mutate_input_even_if_readonly():
    """Вход только для чтения: любая запись в него — ValueError. Заодно содержимое не меняется."""
    rgb = cv2.cvtColor(_photo(), cv2.COLOR_BGR2RGB)
    before = rgb.copy()
    rgb.setflags(write=False)
    mask = tool.gap_alpha_mask(rgb)
    assert mask.shape == rgb.shape[:2] and mask.dtype == np.uint8
    assert np.array_equal(rgb, before)
