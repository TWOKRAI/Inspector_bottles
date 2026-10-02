# -*- coding: utf-8 -*-
"""Task 1.4 (layer-render): фильтр площади `min_area` в `gap_alpha_mask` и флаг CLI `--gap-min-area`.

Слепые приёмочные тесты тестера по Acceptance A1..A5 + A4b (plans/layer-render/phase-1.md, Task 1.4).
Написаны ДО реализации; ожидаемые значения — литералы или строятся независимо от кода под тестом
(самописный BFS по 8-связности, множества пикселей, снятые на коде до задачи sha256).

Цвета синтетики: просвет RGB (0, 200, 0) — H=60, S=255, внутри порогов по умолчанию (H 25..85, S >= 40);
звено RGB (128, 128, 128) — S=0, вне порога. Любой пиксель «просвет» ⇔ ровно цвет _GAP.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode
from Services.line_sim.tools import make_seamless_texture as tool

_GAP = (0, 200, 0)
_LINK = (128, 128, 128)
_NO_RAILS = (0, 0)


def _tile(h: int, w: int, gap: set[tuple[int, int]]) -> np.ndarray:
    """RGB uint8 (h, w, 3): звено везде, цвет просвета в пикселях `gap` (y, x)."""
    img = np.empty((h, w, 3), np.uint8)
    img[:] = _LINK
    for y, x in gap:
        img[y, x] = _GAP
    return img


def _rect(y0: int, x0: int, hh: int, ww: int) -> set[tuple[int, int]]:
    return {(y, x) for y in range(y0, y0 + hh) for x in range(x0, x0 + ww)}


def _components8(gap: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """Независимый от cv2 BFS: компоненты 8-связности множества пикселей."""
    left, comps = set(gap), []
    while left:
        seed = left.pop()
        comp, stack = {seed}, [seed]
        while stack:
            y, x = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nb = (y + dy, x + dx)
                    if nb in left:
                        left.discard(nb)
                        comp.add(nb)
                        stack.append(nb)
        comps.append(comp)
    return comps


def _expected_alpha(h: int, w: int, gap: set[tuple[int, int]], min_area: int, rails: tuple[int, int]) -> np.ndarray:
    """Эталон: сперва борта -> 255 (пиксели борта выпадают из просвета), потом компоненты < min_area -> 255."""
    top, bottom = rails
    alive = {(y, x) for (y, x) in gap if top <= y < h - bottom}
    out = np.full((h, w), 255, np.uint8)
    for comp in _components8(alive):
        if len(comp) >= min_area:
            for y, x in comp:
                out[y, x] = 0
    return out


def _sha(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


# --------------------------------------------------------------------------------------------------
# Синтетический тайл A2: компоненты площади 1, 3, 7, 8, 20, разнесённые с зазором >= 2 px (в т.ч. по диагонали).
# --------------------------------------------------------------------------------------------------
_H2, _W2 = 40, 60
_COMPS = {
    1: _rect(3, 4, 1, 1),
    3: _rect(7, 4, 1, 3),
    7: _rect(11, 4, 1, 7),
    8: _rect(15, 4, 2, 4),
    20: _rect(21, 4, 4, 5),
}
_GAP2 = set().union(*_COMPS.values())


def _tile2() -> np.ndarray:
    return _tile(_H2, _W2, _GAP2)


# --------------------------------------------------------------------------------------------------
# A1. min_area=0 / нет keyword — выход побайтно прежний.
# --------------------------------------------------------------------------------------------------
# sha256 выхода `gap_alpha_mask(_tile2(), rails_px=(0, 0))` — снят на коде ДО задачи (b294a6afe).
_SHA_TILE2_NO_RAILS = "0eba9e939d4524d21f830ce5d8b88d4630753842077af0e5943d0304effacbdd"
# Тайл 60x60 для дефолтных бортов (22, 22): компоненты 1/3/7/8/20 px в строках 22..37 и компонента 3 px в строке 5
# (борт — принудительно 255 ещё до задачи).
_COMPS3 = {
    1: _rect(24, 4, 1, 1),
    3: _rect(28, 4, 1, 3),
    7: _rect(32, 4, 1, 7),
    8: _rect(35, 20, 2, 4),
    20: _rect(24, 30, 4, 5),
}
_GAP3 = set().union(*_COMPS3.values()) | _rect(5, 4, 1, 3)
# sha256 выхода `gap_alpha_mask(_tile3())` с дефолтными бортами — снят на коде ДО задачи.
_SHA_TILE3_DEFAULT_RAILS = "1747af60609fd0a2ed273a8442e590ec8ec2b35034c336318009a748188b35f6"


def _tile3() -> np.ndarray:
    return _tile(60, 60, _GAP3)


def test_a1_no_keyword_matches_pre_task_literal_sha():
    """Отсутствие keyword: выход == литерал до задачи (функция по умолчанию фильтр НЕ применяет)."""
    out = tool.gap_alpha_mask(_tile2(), rails_px=_NO_RAILS)
    assert _sha(out) == _SHA_TILE2_NO_RAILS
    assert int((out == 0).sum()) == 1 + 3 + 7 + 8 + 20


def test_a1_min_area_zero_matches_pre_task_literal_sha():
    """`min_area=0` — тот же литерал (вызов нового keyword внутри теста: до реализации TypeError)."""
    out = tool.gap_alpha_mask(_tile2(), rails_px=_NO_RAILS, min_area=0)
    assert _sha(out) == _SHA_TILE2_NO_RAILS


def test_a1_no_keyword_default_rails_matches_pre_task_literal_sha():
    out = tool.gap_alpha_mask(_tile3())
    assert _sha(out) == _SHA_TILE3_DEFAULT_RAILS
    assert int((out == 0).sum()) == 1 + 3 + 7 + 8 + 20


def test_a1_min_area_zero_with_default_rails_matches_pre_task_literal_sha():
    """С дефолтными бортами (22, 22) и min_area=0 — литерал до задачи; компонента в борту остаётся 255."""
    out = tool.gap_alpha_mask(_tile3(), min_area=0)
    assert _sha(out) == _SHA_TILE3_DEFAULT_RAILS


def test_a1_min_area_one_removes_nothing():
    """Граница: `площадь < 1` не бывает — `min_area=1` выход идентичен выключенному фильтру."""
    out = tool.gap_alpha_mask(_tile2(), rails_px=_NO_RAILS, min_area=1)
    assert _sha(out) == _SHA_TILE2_NO_RAILS


# --------------------------------------------------------------------------------------------------
# A2. Компоненты 1/3/7/8/20, min_area=8: 1/3/7 -> 255, 8 и 20 — как без фильтра, попиксельно.
# --------------------------------------------------------------------------------------------------
def test_a2_min_area_8_removes_1_3_7_keeps_8_and_20_pixel_exact():
    out = tool.gap_alpha_mask(_tile2(), rails_px=_NO_RAILS, min_area=8)
    expected = np.full((_H2, _W2), 255, np.uint8)
    for size in (8, 20):
        for y, x in _COMPS[size]:
            expected[y, x] = 0
    assert np.array_equal(out, expected)
    assert int((out == 0).sum()) == 28


@pytest.mark.parametrize(
    ("min_area", "survivors"),
    [
        (2, (3, 7, 8, 20)),  # 1 < 2 уходит
        (4, (7, 8, 20)),  # 1 и 3 уходят
        (7, (7, 8, 20)),  # 7 не меньше 7 — остаётся (граница включительно)
        (8, (8, 20)),  # 7 уходит
        (9, (20,)),  # 8 уходит
        (20, (20,)),  # 20 не меньше 20 — остаётся
        (21, ()),  # уходит всё
    ],
)
def test_a2_threshold_boundary_is_strictly_less_than(min_area, survivors):
    """Удаляется компонента с площадью СТРОГО меньше `min_area`; границы с двух сторон."""
    out = tool.gap_alpha_mask(_tile2(), rails_px=_NO_RAILS, min_area=min_area)
    gap = set().union(*(_COMPS[s] for s in survivors)) if survivors else set()
    expected = np.full((_H2, _W2), 255, np.uint8)
    for y, x in gap:
        expected[y, x] = 0
    assert np.array_equal(out, expected)


def test_a2_filter_does_not_touch_rgb_input_semantics_only_alpha():
    """Функция возвращает только маску (H, W); компоненты, которые остаются, не сдвигаются и не растут."""
    out = tool.gap_alpha_mask(_tile2(), rails_px=_NO_RAILS, min_area=8)
    assert out.shape == (_H2, _W2)
    ys, xs = np.nonzero(out == 0)
    assert set(zip(ys.tolist(), xs.tolist())) == _COMPS[8] | _COMPS[20]


# --------------------------------------------------------------------------------------------------
# A3. 8-связность.
# --------------------------------------------------------------------------------------------------
_DIAG2 = {(10, 10), (11, 11)}
_ANTI2 = {(11, 10), (10, 11)}
_DIAG4 = {(10, 10), (11, 11), (12, 12), (13, 13)}


@pytest.mark.parametrize("pair", [_DIAG2, _ANTI2], ids=["diag", "anti-diag"])
def test_a3_corner_touching_pair_is_one_component_of_area_2_removed_at_3(pair):
    out = tool.gap_alpha_mask(_tile(24, 24, pair), rails_px=_NO_RAILS, min_area=3)
    assert np.array_equal(out, np.full((24, 24), 255, np.uint8))


@pytest.mark.parametrize("pair", [_DIAG2, _ANTI2], ids=["diag", "anti-diag"])
def test_a3_corner_touching_pair_is_kept_at_2(pair):
    """Площадь 2 не меньше 2: оба пикселя остаются 0 (при 4-связности они бы были двумя по 1 и ушли)."""
    out = tool.gap_alpha_mask(_tile(24, 24, pair), rails_px=_NO_RAILS, min_area=2)
    expected = np.full((24, 24), 255, np.uint8)
    for y, x in pair:
        expected[y, x] = 0
    assert np.array_equal(out, expected)


def test_a3_four_diagonal_pixels_are_one_component_of_area_4():
    tile = _tile(24, 24, _DIAG4)
    kept = tool.gap_alpha_mask(tile, rails_px=_NO_RAILS, min_area=4)
    expected = np.full((24, 24), 255, np.uint8)
    for y, x in _DIAG4:
        expected[y, x] = 0
    assert np.array_equal(kept, expected)
    gone = tool.gap_alpha_mask(tile, rails_px=_NO_RAILS, min_area=5)
    assert np.array_equal(gone, np.full((24, 24), 255, np.uint8))


def test_a3_pixels_with_one_pixel_gap_are_two_components_not_merged():
    """Контроль от «слишком широкой» связности: пиксели через один пустой — две компоненты по 1."""
    tile = _tile(24, 24, {(10, 10), (10, 12)})
    out = tool.gap_alpha_mask(tile, rails_px=_NO_RAILS, min_area=2)
    assert np.array_equal(out, np.full((24, 24), 255, np.uint8))


def test_a3_tile_x_edges_are_not_glued():
    """Край тайла по x не склеивается: по пикселю у x=0 и x=W-1 — две компоненты по 1, при min_area=2 уходят оба."""
    out = tool.gap_alpha_mask(_tile(24, 24, {(10, 0), (10, 23)}), rails_px=_NO_RAILS, min_area=2)
    assert np.array_equal(out, np.full((24, 24), 255, np.uint8))


def test_a3_component_touching_tile_edge_is_counted_by_its_inside_part_only():
    """Площадь у края считается по пикселям тайла: 2 px у левого края при min_area=2 остаются, при 3 уходят."""
    tile = _tile(24, 24, {(10, 0), (10, 1)})
    kept = tool.gap_alpha_mask(tile, rails_px=_NO_RAILS, min_area=2)
    assert int((kept == 0).sum()) == 2
    gone = tool.gap_alpha_mask(tile, rails_px=_NO_RAILS, min_area=3)
    assert int((gone == 0).sum()) == 0


# --------------------------------------------------------------------------------------------------
# A4. Борта 255 при любом min_area; вход не мутирован; uint8 (H, W) из {0, 255}.
# --------------------------------------------------------------------------------------------------
_H4, _W4 = 60, 30
# Полоса цвета просвета шириной 3 на всю высоту: при дефолтных бортах (22, 22) в средних 16 строках — 48 px.
_STRIPE = _rect(0, 10, _H4, 3)


@pytest.mark.parametrize(
    ("min_area", "middle_survives"),
    [(0, True), (1, True), (8, True), (48, True), (49, False), (10**6, False)],
)
def test_a4_rails_rows_are_opaque_for_any_min_area(min_area, middle_survives):
    out = tool.gap_alpha_mask(_tile(_H4, _W4, _STRIPE), min_area=min_area)
    assert np.all(out[:22] == 255) and np.all(out[_H4 - 22 :] == 255)
    middle = out[22 : _H4 - 22]
    if middle_survives:
        # 48 px (16 строк x 3) — одна компонента без пикселей в бортах; площадь >= min_area -> остаётся 0
        assert int((middle == 0).sum()) == 48 and np.all(middle[:, 10:13] == 0)
    else:
        assert np.all(middle == 255)


def test_a4_output_contract_dtype_shape_values():
    out = tool.gap_alpha_mask(_tile2(), rails_px=_NO_RAILS, min_area=8)
    assert out.dtype == np.uint8 and out.shape == (_H2, _W2)
    assert set(np.unique(out).tolist()) == {0, 255}


def test_a4_input_is_not_mutated_even_if_readonly():
    tile = _tile2()
    before = tile.copy()
    tile.setflags(write=False)
    tool.gap_alpha_mask(tile, rails_px=_NO_RAILS, min_area=8)
    assert np.array_equal(tile, before)


# --------------------------------------------------------------------------------------------------
# A4b. Порядок «борта, потом фильтр».
# --------------------------------------------------------------------------------------------------
_H4B, _W4B = 40, 30
_RAILS_4B = (7, 7)


@pytest.mark.parametrize(
    "bar",
    [_rect(0, 10, 10, 1), _rect(30, 10, 10, 1)],
    ids=["top-rail", "bottom-rail"],
)
def test_a4b_rails_are_forced_opaque_before_the_filter_so_remaining_3_px_vanish(bar):
    """Компонента цвета просвета 10 px, 7 из них в строках борта; при min_area=8 оставшиеся 3 -> 255
    (при обратном порядке «фильтр, потом борта» компонента из 10 px выжила бы и 3 px остались бы 0)."""
    out = tool.gap_alpha_mask(_tile(_H4B, _W4B, bar), rails_px=_RAILS_4B, min_area=8)
    assert np.array_equal(out, np.full((_H4B, _W4B), 255, np.uint8))


@pytest.mark.parametrize(
    "bar",
    [_rect(0, 10, 10, 1), _rect(30, 10, 10, 1)],
    ids=["top-rail", "bottom-rail"],
)
def test_a4b_control_same_bar_keeps_its_3_px_at_min_area_3(bar):
    """Контроль от пустоты: при min_area=3 те же 3 px вне борта остаются 0 — тест выше проверяет именно порядок."""
    out = tool.gap_alpha_mask(_tile(_H4B, _W4B, bar), rails_px=_RAILS_4B, min_area=3)
    expected = _expected_alpha(_H4B, _W4B, bar, 3, _RAILS_4B)
    assert int((expected == 0).sum()) == 3
    assert np.array_equal(out, expected)


# --------------------------------------------------------------------------------------------------
# Свойство-оракул: случайные тайлы против независимого BFS (борта -> потом фильтр, 8-связность).
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(25))
def test_random_tiles_match_independent_oracle(seed):
    rng = np.random.default_rng(seed)
    h, w = int(rng.integers(10, 22)), int(rng.integers(10, 22))
    density = float(rng.choice([0.1, 0.25, 0.4]))
    gap = {(y, x) for y in range(h) for x in range(w) if rng.random() < density}
    rails = (int(rng.integers(0, 3)), int(rng.integers(0, 3)))
    min_area = int(rng.integers(0, 12))
    out = tool.gap_alpha_mask(_tile(h, w, gap), rails_px=rails, min_area=min_area)
    assert np.array_equal(out, _expected_alpha(h, w, gap, min_area, rails))


# --------------------------------------------------------------------------------------------------
# A5. CLI.
# --------------------------------------------------------------------------------------------------
_PH, _PW = 60, 100
_CLI_3PX = _rect(28, 30, 1, 3)
_CLI_8PX = _rect(28, 60, 2, 4)
_CLI_GAP = _CLI_3PX | _CLI_8PX


def _cli_photo() -> np.ndarray:
    """BGR (60, 100, 3): звено везде, два просвета (3 px и 8 px) в строках 28..29 — вне бортов (22, 22).
    Цвет просвета (0, 200, 0) одинаков в RGB и BGR (R = B = 0)."""
    return cv2.cvtColor(_tile(_PH, _PW, _CLI_GAP), cv2.COLOR_RGB2BGR)


def _write_photo(tmp_path: Path) -> Path:
    src = tmp_path / "photo.png"
    imwrite_unicode(str(src), _cli_photo())
    return src


def _run(tmp_path: Path, name: str, *extra: str) -> np.ndarray:
    out = tmp_path / name
    rc = tool.main([str(_write_photo(tmp_path)), "--out", str(out), *extra])
    assert rc == 0
    return imread_unicode(str(out), cv2.IMREAD_UNCHANGED)


def _rgb_gap_pixels(png: np.ndarray) -> set[tuple[int, int]]:
    """Пиксели цвета просвета в RGB-части записанного тайла (RGB не меняется фильтром — это якорь оракула)."""
    rgb = cv2.cvtColor(np.ascontiguousarray(png[:, :, :3]), cv2.COLOR_BGR2RGB)
    ys, xs = np.nonzero(np.all(rgb == np.array(_GAP, np.uint8), axis=2))
    return set(zip(ys.tolist(), xs.tolist()))


def _zero_sizes(alpha: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(alpha == 0)
    return sorted(len(c) for c in _components8(set(zip(ys.tolist(), xs.tolist()))))


def _oracle_alpha(png: np.ndarray, min_area: int) -> np.ndarray:
    h, w = png.shape[:2]
    return _expected_alpha(h, w, _rgb_gap_pixels(png), min_area, (22, 22))


def test_cli_anchor_photo_contains_a_3px_and_an_8px_gap_component_in_the_output_tile(tmp_path):
    """Якорь против пустоты: независимо от пути (period/mirror) в выходном RGB есть компоненты 3 и 8 px."""
    png = _run(tmp_path, "anchor.png")
    sizes = sorted(len(c) for c in _components8(_rgb_gap_pixels(png)))
    assert sizes == [3, 8]


def test_a5_cli_default_threshold_is_8_small_component_gone_8px_stays(tmp_path):
    png = _run(tmp_path, "t.png", "--gap-alpha")
    alpha = png[:, :, 3]
    sizes = _zero_sizes(alpha)
    assert sizes and min(sizes) == 8, f"размеры прозрачных компонент: {sizes}"
    assert np.array_equal(alpha, _oracle_alpha(png, 8))


def test_a5_cli_explicit_8_equals_default(tmp_path):
    default = _run(tmp_path, "d.png", "--gap-alpha")
    explicit = _run(tmp_path, "e.png", "--gap-alpha", "--gap-min-area", "8")
    assert np.array_equal(default, explicit)


def test_a5_cli_min_area_zero_keeps_the_3px_component_and_equals_oracle(tmp_path):
    png = _run(tmp_path, "z.png", "--gap-alpha", "--gap-min-area", "0")
    alpha = png[:, :, 3]
    sizes = _zero_sizes(alpha)
    assert 3 in sizes and 8 in sizes
    assert np.array_equal(alpha, _oracle_alpha(png, 0))


# sha256 байтов декодированного RGBA-массива CLI `--gap-alpha` на этой фотографии — снят на коде ДО задачи
# (тогда флага нет и фильтра нет — выход равен `--gap-min-area 0`).
_SHA_CLI_PRE_TASK = "0c42ac14cba93b38128b7c4156fa2a492335355df8d225660f27f69c91448c22"


def test_a5_cli_min_area_zero_equals_pre_task_literal_sha(tmp_path):
    png = _run(tmp_path, "z.png", "--gap-alpha", "--gap-min-area", "0")
    assert png.ndim == 3 and png.shape[2] == 4
    assert _sha(png) == _SHA_CLI_PRE_TASK


def test_a5_cli_rgb_channels_identical_with_and_without_filter(tmp_path):
    filtered = _run(tmp_path, "f.png", "--gap-alpha")
    unfiltered = _run(tmp_path, "u.png", "--gap-alpha", "--gap-min-area", "0")
    assert not np.array_equal(filtered[:, :, 3], unfiltered[:, :, 3]), "фильтр ничего не изменил — тест пуст"
    assert np.array_equal(filtered[:, :, :3], unfiltered[:, :, :3])


def test_a5_cli_rgb_channels_equal_output_without_gap_alpha(tmp_path):
    """Фильтр трогает только альфу: RGB RGBA-выхода с порогом == тайл без `--gap-alpha`."""
    filtered = _run(tmp_path, "f.png", "--gap-alpha")
    plain = _run(tmp_path, "p.png")
    assert np.array_equal(filtered[:, :, :3], plain)


def _err(capsys) -> str:
    return capsys.readouterr().err.rsplit("error:", 1)[1]


def test_a5_cli_gap_min_area_without_gap_alpha_is_an_error_naming_both_flags(tmp_path, capsys):
    out = tmp_path / "o.png"
    with pytest.raises(SystemExit) as info:
        tool.main([str(_write_photo(tmp_path)), "--out", str(out), "--gap-min-area", "8"])
    assert info.value.code not in (0, None)
    err = _err(capsys)
    # «unrecognized arguments» — это argparse до реализации флага, а не проверка инструмента.
    assert "unrecognized" not in err
    assert "--gap-min-area" in err and "--gap-alpha" in err
    assert not out.exists()


@pytest.mark.parametrize("value", ["-1", "abc", "", "2.5"])
def test_a5_cli_bad_gap_min_area_value_is_an_error_naming_the_flag(tmp_path, capsys, value):
    out = tmp_path / "o.png"
    with pytest.raises(SystemExit) as info:
        tool.main([str(_write_photo(tmp_path)), "--out", str(out), "--gap-alpha", f"--gap-min-area={value}"])
    assert info.value.code not in (0, None)
    err = _err(capsys)
    assert "unrecognized" not in err
    assert "--gap-min-area" in err
    assert not out.exists()
