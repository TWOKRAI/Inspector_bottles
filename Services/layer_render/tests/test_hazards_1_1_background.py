# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.1 `layer_render`: что ломается в самом механизме свёртки и рисования.

Опасные места: (1) свёртка обязана совпадать с общим путём пиксель в пиксель — иначе ускорение меняет
картинку; (2) знак `scroll_px`; (3) тайл выше кадра и смещённое окно камеры; (4) входные массивы нельзя
менять — ни свёрткой, ни рисованием; (5) пустой стек — чёрный кадр, а не мусор в буфере.
Независимый оракул — наивный попиксельный цикл (формула «over» записана литералом, не импортирована).
"""

from __future__ import annotations

import numpy as np
import pytest

from Services.layer_render import (
    ScrollingTile,
    SolidFill,
    background_layers_from_config,
    fold_background,
    render_background,
)


def _naive(layers, h, w, scroll_px, origin_xy, center_y) -> np.ndarray:
    """Оракул: попиксельно, снизу вверх, без numpy-индексации."""
    ox, oy = origin_xy
    out = [[(0, 0, 0)] * w for _ in range(h)]
    for layer in layers:
        if isinstance(layer, SolidFill):
            out = [[tuple(layer.color_rgb)] * w for _ in range(h)]
            continue
        img = layer.image
        th, tw = img.shape[:2]
        top = int(round(center_y - th / 2))
        for y in range(h):
            ty = y + oy - top
            if not 0 <= ty < th:
                continue
            for x in range(w):
                px = [int(v) for v in img[ty, (x + ox - scroll_px) % tw]]
                a = px[3] if len(px) == 4 else 255
                out[y][x] = tuple((a * px[c] + (255 - a) * out[y][x][c] + 127) // 255 for c in range(3))
    return np.array(out, dtype=np.uint8).reshape(h, w, 3)


def _rand_tile(rng, th, tw, channels) -> np.ndarray:
    return rng.integers(0, 256, size=(th, tw, channels), dtype=np.uint8)


def _draw(layers, h=23, w=31, scroll_px=0, origin_xy=(0, 0), center_y=11.0) -> np.ndarray:
    frame = np.full((h, w, 3), 77, dtype=np.uint8)  # мусор в буфере: рисование обязано его затереть
    render_background(frame, layers, scroll_px=scroll_px, origin_xy=origin_xy, center_y=center_y)
    return frame


@pytest.mark.parametrize("seed", range(12))
def test_fold_equals_general_path_and_naive_oracle_on_random_rgba_stacks(seed):
    rng = np.random.default_rng(seed)
    layers: list = []
    for _ in range(int(rng.integers(1, 6))):
        if rng.random() < 0.35:
            layers.append(SolidFill(color_rgb=tuple(int(v) for v in rng.integers(0, 256, 3))))
        else:
            layers.append(
                ScrollingTile(
                    image=_rand_tile(rng, int(rng.integers(1, 40)), int(rng.integers(1, 17)), int(rng.choice([3, 4])))
                )
            )
    # у половины прогонов — два RGBA-тайла подряд поверх подложки (запекается первый, второй идёт общим путём)
    if seed % 2:
        layers += [ScrollingTile(image=_rand_tile(rng, 15, 9, 4)), ScrollingTile(image=_rand_tile(rng, 30, 5, 4))]
    kw = dict(scroll_px=int(rng.integers(-60, 60)), origin_xy=(int(rng.integers(-9, 9)), int(rng.integers(-9, 9))))
    center_y = float(rng.integers(0, 30)) + 0.5
    general = _draw(layers, center_y=center_y, **kw)
    folded = _draw(fold_background(layers), center_y=center_y, **kw)
    assert np.array_equal(folded, general), "свёртка изменила картинку"
    assert np.array_equal(general, _naive(layers, 23, 31, kw["scroll_px"], kw["origin_xy"], center_y)), (
        "общий путь != оракул"
    )


def test_fold_result_shape_solid_then_opaque_rgb_tile_then_remaining_tiles():
    rng = np.random.default_rng(0)
    t1, t2 = _rand_tile(rng, 5, 5, 4), _rand_tile(rng, 5, 5, 4)
    folded = fold_background([SolidFill((9, 9, 9)), SolidFill((1, 2, 3)), ScrollingTile(t1), ScrollingTile(t2)])
    assert [type(x) for x in folded] == [SolidFill, ScrollingTile, ScrollingTile]
    assert folded[0].color_rgb == (1, 2, 3), "верхний solid прячет нижний"
    assert folded[1].image.shape == (5, 5, 3)
    assert folded[2].image is t2
    assert [type(x) for x in fold_background([])] == [SolidFill]


def test_alpha_0_and_255_are_exact_not_within_one():
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[:, :2] = (250, 3, 99, 255)
    rgba[:, 2:] = (250, 3, 99, 0)
    frame = _draw([SolidFill((11, 222, 33)), ScrollingTile(rgba)], h=4, w=4, center_y=2.0)
    assert (frame[:, :2] == (250, 3, 99)).all()
    assert (frame[:, 2:] == (11, 222, 33)).all()


def test_scroll_px_sign_positive_moves_tile_content_to_the_right():
    tw = 7
    tile = np.zeros((3, tw, 3), dtype=np.uint8)
    tile[:, :, 0] = np.arange(tw) * 10  # R кодирует индекс столбца тайла
    layers = [ScrollingTile(tile)]
    base = _draw(layers, h=3, w=tw, center_y=1.5)
    assert list(base[0, :, 0]) == [0, 10, 20, 30, 40, 50, 60]
    right = _draw(layers, h=3, w=tw, scroll_px=2, center_y=1.5)
    assert list(right[0, :, 0]) == [50, 60, 0, 10, 20, 30, 40]  # столбец 0 тайла переехал на x=2
    left = _draw(layers, h=3, w=tw, scroll_px=-2, center_y=1.5)
    assert list(left[0, :, 0]) == [20, 30, 40, 50, 60, 0, 10]


def test_scroll_by_whole_tile_widths_is_identity_and_negative_origin_wraps():
    rng = np.random.default_rng(3)
    layers = [SolidFill((1, 1, 1)), ScrollingTile(_rand_tile(rng, 10, 6, 4))]
    ref = _draw(layers, center_y=11.0)
    assert np.array_equal(_draw(layers, scroll_px=6 * 5, center_y=11.0), ref)
    assert np.array_equal(_draw(layers, origin_xy=(-6 * 4, 0), center_y=11.0), ref)


@pytest.mark.parametrize("origin_y", [0, 7, -5])
@pytest.mark.parametrize("channels", [3, 4])
def test_tile_taller_than_frame_and_shifted_camera_window_match_oracle(origin_y, channels):
    rng = np.random.default_rng(origin_y + 10)
    layers = [SolidFill((5, 6, 7)), ScrollingTile(_rand_tile(rng, 61, 8, channels))]  # 61 > кадра 23
    got = _draw(layers, scroll_px=3, origin_xy=(2, origin_y), center_y=20.0)
    assert np.array_equal(got, _naive(layers, 23, 31, 3, (2, origin_y), 20.0))


def test_tile_fully_outside_frame_rows_leaves_layer_below_untouched():
    layers = [SolidFill((5, 6, 7)), ScrollingTile(np.full((4, 4, 3), 200, dtype=np.uint8))]
    frame = _draw(layers, h=10, w=10, center_y=100.0)  # полоса тайла далеко ниже кадра
    assert (frame == (5, 6, 7)).all()


def test_inputs_are_not_mutated_by_fold_or_render():
    rng = np.random.default_rng(1)
    rgb, rgba = _rand_tile(rng, 12, 7, 3), _rand_tile(rng, 12, 7, 4)
    layers = [SolidFill((1, 2, 3)), ScrollingTile(rgb), ScrollingTile(rgba)]
    before = (rgb.copy(), rgba.copy(), list(layers))
    folded = fold_background(layers)
    _draw(layers)
    _draw(folded)
    assert np.array_equal(rgb, before[0]) and np.array_equal(rgba, before[1])
    assert layers == before[2]
    # свёрнутый RGB-тайл — копия: правка снаружи не должна просочиться в свёрнутый стек
    rgb_only = fold_background([ScrollingTile(rgb)])
    rgb[0, 0] = 255 - before[0][0, 0]
    assert tuple(rgb_only[1].image[0, 0]) == tuple(before[0][0, 0])


def test_all_tiles_dropped_gives_empty_stack_and_black_frame_over_garbage_buffer():
    layers = background_layers_from_config([{"tile": "a.png"}, {"tile": "b.png"}], lambda p: None)
    assert layers == []
    frame = _draw(fold_background(layers))
    assert (frame == 0).all()


def test_loader_is_not_called_when_schema_is_bad_and_dropped_tile_keeps_order_of_the_rest():
    calls: list[str] = []

    def load(path):
        calls.append(path)
        return None if path == "gone.png" else np.zeros((2, 2, 3), dtype=np.uint8)

    with pytest.raises(ValueError):
        background_layers_from_config([{"tile": "a.png"}, {"solid": [1, 2, 300]}], load)
    assert calls == [], "схема проверяется целиком ДО загрузки картинок"
    layers = background_layers_from_config([{"solid": [1, 2, 3]}, {"tile": "gone.png"}, {"tile": "ok.png"}], load)
    assert [type(x) for x in layers] == [SolidFill, ScrollingTile]
    assert calls == ["gone.png", "ok.png"]


@pytest.mark.parametrize("color", [[True, 0, 0], [0, False, 0]])
def test_bool_color_channel_is_rejected(color):
    with pytest.raises(ValueError):
        background_layers_from_config([{"solid": color}], lambda p: None)
