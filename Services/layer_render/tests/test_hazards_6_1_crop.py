# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 6.1: внутренние места `crop.py`, видимые только изнутри (дополнение к слепому набору).

Что здесь может сломаться: квадрат больше кадра, нечётная сторона, read-only кадр (SHM), 2D/4-канальный холст,
порядок проверок (неизвестный `oob` внутри кадра), маппинг регистра плагина, поведение `_crop_disk` на выходе
центра за кадр. Ожидаемые значения — литералы или независимый `np.pad`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from Services.layer_render.crop import resize_square, side_from_radius, square_crop


def _frame(h: int = 20, w: int = 16, c: int = 3) -> np.ndarray:
    y = np.arange(h)[:, None, None]
    x = np.arange(w)[None, :, None]
    ch = np.arange(c)[None, None, :]
    return ((y * 11 + x * 5 + ch * 3 + 1) % 256).astype(np.uint8)


def _ro(a: np.ndarray) -> np.ndarray:
    a.flags.writeable = False
    return a


@pytest.mark.parametrize("oob", ["pad", "clamp", "replicate"])
def test_square_much_larger_than_frame_keeps_whole_frame_in_place(oob):
    """side=100 на кадре 20x16: кадр целиком внутри квадрата, смещение = -x0 (центр кадра)."""
    f = _frame()
    out = square_crop(f, 8, 10, 100, oob, pad_value=(1, 2, 3))
    if oob == "clamp":
        assert np.array_equal(out, f)  # весь кадр, без полей
        return
    assert out.shape == (100, 100, 3)
    x0, y0 = 8 - 50, 10 - 50  # -42, -40
    assert np.array_equal(out[-y0 : -y0 + 20, -x0 : -x0 + 16], f)
    if oob == "pad":
        assert (out[0, 0] == (1, 2, 3)).all() and (out[99, 99] == (1, 2, 3)).all()
    else:
        assert (out[0, 0] == f[0, 0]).all() and (out[99, 99] == f[19, 15]).all()


@pytest.mark.parametrize("oob", ["pad", "replicate"])
def test_odd_side_has_exact_size_and_anchor_at_left_edge(oob):
    """Нечётная сторона 7: x0 = cx - 3, ширина ровно 7 (не 6 и не 8) и при сдвиге за край."""
    f = _frame()
    out = square_crop(f, 1, 10, 7, oob, pad_value=(9, 9, 9))  # x0 = -2
    assert out.shape == (7, 7, 3)
    assert np.array_equal(out[:, 2:], f[7:14, 0:5])  # 5 столбцов кадра на месте


def test_unknown_oob_checked_before_work_even_for_degenerate_input():
    """Проверка режима стоит до раннего возврата «внутри кадра»: опечатка не молчит ни на каком входе."""
    with pytest.raises(ValueError, match="clamped"):
        square_crop(_frame(), 8, 10, 4, "clamped")


@pytest.mark.parametrize("oob", ["drop", "pad", "clamp", "replicate"])
def test_read_only_frame_never_leaks_a_view(oob):
    """Read-only кадр (SHM): выход записываемый, память не общая — и внутри кадра, и на границе."""
    for cx, cy in ((8, 10), (1, 1)):
        f = _ro(_frame())
        out = square_crop(f, cx, cy, 8, oob, pad_value=(0, 0, 0))
        if out is None:
            continue
        assert out.flags.writeable and not np.shares_memory(out, f)


def test_pad_two_dim_and_four_channel_canvases_follow_frame_format():
    """2D: pad_value[0]; 4 канала: (b, g, r, 0); dtype кадра сохраняется."""
    f2 = _frame(c=1)[:, :, 0]
    out2 = square_crop(f2, -10, 10, 4, "pad", pad_value=(7, 8, 9))
    assert out2.shape == (4, 4) and (out2 == 7).all()
    f4 = _frame(c=4)
    out4 = square_crop(f4, 8, -10, 4, "pad", pad_value=(7, 8, 9))
    assert out4.shape == (4, 4, 4) and (out4 == np.array([7, 8, 9, 0], dtype=np.uint8)).all()
    f16 = _frame().astype(np.uint16)
    assert square_crop(f16, -10, 10, 4, "pad").dtype == np.uint16


def test_replicate_matches_edge_pad_for_a_corner_overlap():
    """Угол: один пиксель перекрытия (cx=-1, cy=-1, side=4 -> x1=1, y1=1) = np.pad(edge) от кадра 1x1."""
    f = _frame()
    out = square_crop(f, -1, -1, 4, "replicate")
    assert np.array_equal(out, np.broadcast_to(f[0, 0], (4, 4, 3)))


def test_resize_square_does_not_touch_its_input():
    """Входной (read-only) вырез не мутируется ресайзом."""
    c = _ro(_frame(40, 40))
    before = c.copy()
    out = resize_square(c, 16)
    assert out.shape == (16, 16, 3) and np.array_equal(c, before)


def test_side_from_radius_floor_with_negative_margin():
    """Отрицательные поля не уводят сторону ниже 2."""
    assert side_from_radius(1, 1.0, -50) == 2


# --- плагин: маппинг регистра -> oob ------------------------------------------------------------------------------


def _plugin(cfg: dict):
    from Plugins.processing.center_crop.plugin import CenterCropPlugin

    ctx = MagicMock()
    ctx.config = dict(cfg)
    p = CenterCropPlugin()
    p.configure(ctx)
    return p


@pytest.mark.parametrize(
    ("drop", "pad", "expected"),
    [(True, True, "drop"), (True, False, "drop"), (False, True, "pad"), (False, False, "clamp")],
)
def test_register_to_oob_mapping(drop, pad, expected):
    """drop_partial побеждает pad_if_oob; оба выключены -> clamp."""
    assert _plugin({"drop_partial": drop, "pad_if_oob": pad})._oob_mode() == expected


def test_plugin_passes_register_pad_colour_through():
    """pad_color_bgr доходит до холста (а не нули по умолчанию square_crop)."""
    p = _plugin({"drop_partial": False, "pad_if_oob": True, "pad_color_bgr": [4, 5, 6]})
    out = p._crop_square(_frame(), 8, -50, 6)
    assert (out == np.array([4, 5, 6], dtype=np.uint8)).all()


# --- holdout_eval._crop_disk ---------------------------------------------------------------------------------------


def test_crop_disk_is_a_copy_and_side_formula_is_unchanged(monkeypatch):
    """Внутри кадра: сторона 2*round(r*(1+margin)) = 2*round(25*1.2)=60, не view (изменение 6.1)."""
    import Services.ml_train.holdout_eval as he

    f = _ro(_frame(100, 100))
    monkeypatch.setattr(he, "detect_disk", lambda bgr: (50, 50, 25))
    out = he._crop_disk(f, 0.2)
    assert out.shape == (60, 60, 3) and not np.shares_memory(out, f)
    assert np.array_equal(out, f[20:80, 20:80])


def test_crop_disk_center_outside_frame_raises_value_error(monkeypatch):
    """Центр диска целиком вне кадра -> ValueError (раньше молча отдавалось мусорное по форме)."""
    import Services.ml_train.holdout_eval as he

    monkeypatch.setattr(he, "detect_disk", lambda bgr: (50, -200, 25))
    with pytest.raises(ValueError):
        he._crop_disk(_frame(100, 100), 0.2)
