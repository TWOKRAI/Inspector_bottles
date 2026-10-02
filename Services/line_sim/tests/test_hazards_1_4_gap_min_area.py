# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.4 (`min_area` / `--gap-min-area`): что может сломаться в ЭТОМ механизме.

Слепые приёмочные тесты — в `test_acceptance_layer_render_1_4_gap_min_area.py`; здесь только то, что видно
автору: вход не мутируется, `min_area=1` и отрицательный — не фильтр, компонента ровно в `min_area` px
выживает при любой форме, фильтр не считает площадь бортов, сочетание флагов CLI (`--gap-hue` +
`--gap-min-area`) доходит до записанной альфы и не подменяет соседние пороги.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode
from Services.line_sim.tools import make_seamless_texture as tool

_GAP = (0, 200, 0)  # H=60, S=255 — внутри дефолтного порога просвета
_LINK = (128, 128, 128)
_NO_RAILS = (0, 0)


def _tile(h: int, w: int, cells: set[tuple[int, int]]) -> np.ndarray:
    img = np.full((h, w, 3), _LINK, np.uint8)
    for y, x in cells:
        img[y, x] = _GAP
    return img


def _rect(y0: int, x0: int, hh: int, ww: int) -> set[tuple[int, int]]:
    return {(y, x) for y in range(y0, y0 + hh) for x in range(x0, x0 + ww)}


def _zero_cells(mask: np.ndarray) -> set[tuple[int, int]]:
    ys, xs = np.nonzero(mask == 0)
    return set(zip(ys.tolist(), xs.tolist(), strict=True))


# --- функция -------------------------------------------------------------------------------------------


def test_input_not_mutated_and_output_is_a_new_array():
    rgb = _tile(20, 30, _rect(2, 2, 1, 3) | _rect(8, 8, 3, 4))
    before = rgb.copy()
    rgb.setflags(write=False)
    out = tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=8)
    assert rgb.tobytes() == before.tobytes()
    assert out.base is None or not np.shares_memory(out, rgb)


def test_min_area_one_is_a_no_op_on_a_noisy_tile():
    """Площадь любой компоненты >= 1, значит `< 1` не отбрасывает ничего: выход == min_area=0 побайтно."""
    rng = np.random.default_rng(14)
    cells = {(int(y), int(x)) for y, x in zip(rng.integers(0, 40, 300), rng.integers(0, 60, 300), strict=True)}
    rgb = _tile(40, 60, cells)
    off = tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=0)
    assert (off == 0).any()
    assert tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=1).tobytes() == off.tobytes()


def test_negative_min_area_behaves_as_filter_off():
    rgb = _tile(20, 30, _rect(2, 2, 1, 1) | _rect(8, 8, 3, 4))
    off = tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=0)
    assert tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=-5).tobytes() == off.tobytes()


@pytest.mark.parametrize("shape", [(1, 8), (8, 1), (2, 4), (4, 2)])
def test_component_exactly_min_area_survives_for_any_shape_and_dies_one_above(shape):
    cells = _rect(5, 5, *shape)
    assert len(cells) == 8
    rgb = _tile(20, 20, cells)
    assert _zero_cells(tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=8)) == cells
    assert _zero_cells(tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=9)) == set()


def test_min_area_larger_than_every_component_makes_everything_opaque():
    rgb = _tile(20, 30, _rect(2, 2, 3, 3) | _rect(10, 10, 4, 4))
    assert (tool.gap_alpha_mask(rgb, rails_px=_NO_RAILS, min_area=10_000) == 255).all()


def test_large_component_survives_while_small_neighbours_vanish():
    big, small = _rect(3, 3, 6, 6), {(15, 15), (15, 17)}  # 36 px против двух одиночек (не связаны: зазор 1 px)
    assert _zero_cells(tool.gap_alpha_mask(_tile(20, 30, big | small), rails_px=_NO_RAILS, min_area=8)) == big


def test_rails_rows_do_not_count_toward_area():
    """Компонента по цвету 6x6=36 px (строки 6..11), из них строки 6..7 — в борту: остаток 24 px.
    min_area=30: при порядке «борта, потом фильтр» остаток (24 < 30) исчезает; при обратном порядке
    площадь 36 >= 30 и полоса строк 8..11 осталась бы."""
    rgb = _tile(20, 10, _rect(6, 2, 6, 6))
    assert (tool.gap_alpha_mask(rgb, rails_px=(8, 8), min_area=30) == 255).all()
    assert _zero_cells(tool.gap_alpha_mask(rgb, rails_px=(8, 8), min_area=24)) == _rect(8, 2, 4, 6)  # ровно 24 — жив


# --- CLI: сочетание флагов -----------------------------------------------------------------------------

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


def _run(tmp_path: Path, *extra: str) -> np.ndarray:
    src, out = tmp_path / "photo.png", tmp_path / "tile.png"
    imwrite_unicode(str(src), _photo())
    base = [str(src), "--out", str(out), "--scene-px-per-mm", "0.5", "--photo-width-mm", "400", "--gap-alpha"]
    assert tool.main([*base, *extra]) == 0
    return imread_unicode(str(out), cv2.IMREAD_UNCHANGED)


def _expect_alpha(shipped: np.ndarray, **kw) -> np.ndarray:
    rgb = cv2.cvtColor(np.ascontiguousarray(shipped[:, :, :3]), cv2.COLOR_BGR2RGB)
    return tool.gap_alpha_mask(rgb, **kw)


def test_gap_hue_and_min_area_flags_combine_into_the_written_alpha(tmp_path):
    """Оба флага вместе: альфа файла == функция с теми же hue и min_area, остальные пороги дефолтные."""
    plain = _run(tmp_path, "--gap-hue", "30,80", "--gap-min-area", "0")
    assert (plain[:, :, 3] == 0).any(), "контроль: без фильтра на тайле есть просветы"
    assert np.array_equal(plain[:, :, 3], _expect_alpha(plain, hue=(30, 80), min_area=0))

    huge = _run(tmp_path, "--gap-hue", "30,80", "--gap-min-area", "100000")
    assert (huge[:, :, 3] == 255).all(), "порог больше любой компоненты — всё непрозрачно"
    assert np.array_equal(huge[:, :, :3], plain[:, :, :3]), "RGB не должен зависеть от фильтра"


def _run_with_specks(tmp_path: Path, *extra: str) -> np.ndarray:
    """Фото без масштаба, на каждом звене 2x2 мятная «крапинка» (4 px < 8): фильтр что-то да убирает."""
    photo = _photo()
    for k in range(10):
        photo[40:42, k * _P + 14 : k * _P + 16] = (130, 160, 120)
    src, out = tmp_path / "photo.png", tmp_path / "tile.png"
    imwrite_unicode(str(src), photo)
    assert tool.main([str(src), "--out", str(out), "--gap-alpha", *extra]) == 0
    return imread_unicode(str(out), cv2.IMREAD_UNCHANGED)


def test_gap_hue_alone_keeps_the_tool_default_threshold_8(tmp_path):
    """`--gap-hue` без `--gap-min-area`: порог инструмента 8 (крапинки 4 px убраны), а не 0."""
    default = _run_with_specks(tmp_path, "--gap-hue", "30,80")
    off = _run_with_specks(tmp_path, "--gap-hue", "30,80", "--gap-min-area", "0")
    assert (off[:, :, 3] == 0).sum() > (default[:, :, 3] == 0).sum(), "дефолт не убрал крапинки"
    assert np.array_equal(default[:, :, 3], _expect_alpha(default, hue=(30, 80), min_area=8))
    assert np.array_equal(
        default[:, :, 3], _run_with_specks(tmp_path, "--gap-hue", "30,80", "--gap-min-area", "8")[:, :, 3]
    )
    assert tool._GAP_MIN_AREA == 8


@pytest.mark.parametrize("flags", [["--gap-min-area", "5"], ["--gap-hue", "30,80", "--gap-min-area", "5"]])
def test_min_area_without_gap_alpha_is_an_error_naming_a_flag(tmp_path, flags, capsys):
    src = tmp_path / "photo.png"
    imwrite_unicode(str(src), _photo())
    with pytest.raises(SystemExit) as exc:
        tool.main([str(src), "--out", str(tmp_path / "t.png"), *flags])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "--gap-min-area" in err or "--gap-hue" in err
    assert not (tmp_path / "t.png").exists()


@pytest.mark.parametrize("raw", ["-1", "abc", "3.5", ""])
def test_bad_min_area_value_is_an_error_naming_the_flag(tmp_path, raw, capsys):
    src = tmp_path / "photo.png"
    imwrite_unicode(str(src), _photo())
    with pytest.raises(SystemExit):
        tool.main([str(src), "--out", str(tmp_path / "t.png"), "--gap-alpha", "--gap-min-area", raw])
    assert "--gap-min-area" in capsys.readouterr().err
