"""Слепые приёмочные тесты Task 1.2 (критерии 5-7): серый кадр и ``label_scale`` в `overlay_draw`.

Написаны ДО реализации по `plans/code-reader-gui/phase-1.md`, Task 1.2.
Реализацию `plugin.py` автор не читал: только публичный контракт (README, спека)
и образец построения плагина из соседнего ``test_plugin.py``.

Эталон для критерия 7 снят запуском ТЕКУЩЕГО (до правки) плагина на фиксированном
входе (seed 12345), см. ``_LEGACY_*`` ниже. Эталон привязан к версиям opencv 5.0.0 /
numpy 2.4.4: смена версии opencv может сдвинуть антиалиасинг и шрифт -> снимать заново
ТЕМ ЖЕ кодом до правки, не подгонять под новый вывод.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import cv2
import numpy as np

from Plugins.render.overlay_draw.plugin import OverlayDrawPlugin


def _make_plugin(**reg_overrides) -> OverlayDrawPlugin:
    p = OverlayDrawPlugin()
    ctx = MagicMock()
    ctx.registers = None
    ctx.config = reg_overrides
    ctx.log_info = MagicMock()
    p.configure(ctx)
    return p


def _render(frame: np.ndarray, overlay: dict, **cfg) -> np.ndarray:
    out = _make_plugin(**cfg).process([{"frame": frame, "overlay": overlay}])
    assert len(out) == 1
    return out[0]["frame"]


# --------------------------------------------------------------------------
# Критерий 5: серый кадр uint8 (1024, 1280) -> BGR (1024, 1280, 3)
# --------------------------------------------------------------------------

GRAY_LEVEL = 90
RED_BGR = (0, 0, 255)
_LINE_OVERLAY = {"lines": [{"p1": [100, 500], "p2": [1000, 500], "color": [0, 0, 255], "thickness": 4}]}


def _gray_frame() -> np.ndarray:
    return np.full((1024, 1280), GRAY_LEVEL, dtype=np.uint8)


def test_gray_frame_gives_three_channel_output():
    out = _render(_gray_frame(), _LINE_OVERLAY)

    assert out.shape == (1024, 1280, 3)
    assert out.dtype == np.uint8


def test_gray_frame_pixel_on_line_is_pure_red():
    out = _render(_gray_frame(), _LINE_OVERLAY)

    assert out.shape == (1024, 1280, 3)  # предусловие: иначе индексация ниже ничего не значит
    assert tuple(out[500, 500]) == RED_BGR
    assert tuple(out[500, 900]) == RED_BGR


def test_gray_frame_pixel_off_line_keeps_brightness_in_all_three_channels():
    out = _render(_gray_frame(), _LINE_OVERLAY)

    assert out.shape == (1024, 1280, 3)
    assert tuple(out[800, 500]) == (GRAY_LEVEL, GRAY_LEVEL, GRAY_LEVEL)
    assert tuple(out[100, 100]) == (GRAY_LEVEL, GRAY_LEVEL, GRAY_LEVEL)
    # вся строка далеко от линии (y=800) — серая во всех трёх каналах
    assert np.all(out[800] == GRAY_LEVEL)


def test_gray_frame_input_is_not_mutated():
    gray = _gray_frame()
    _render(gray, _LINE_OVERLAY)

    assert gray.shape == (1024, 1280)
    assert gray.dtype == np.uint8
    assert np.all(gray == GRAY_LEVEL)


def test_gray_frame_renders_same_as_its_bgr_copy():
    """Метаморфное: серый кадр рисуется ровно так же, как его BGR-копия (gray -> BGR)."""
    gray = np.random.default_rng(777).integers(0, 256, (480, 640), dtype=np.uint8)
    overlay = {
        "lines": [{"p1": [50, 60], "p2": [600, 400], "color": [0, 0, 255]}],
        "points": [{"xy": [100, 100], "label": "QR-15MM"}],
    }
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    assert np.array_equal(_render(gray, overlay), _render(bgr, overlay))


# --------------------------------------------------------------------------
# Критерий 6: label_scale масштабирует подпись
# --------------------------------------------------------------------------

_LABEL_TEXT = "QR-15MM test label"
_BAND = (slice(100, 320), slice(0, 640))  # строки, столбцы вокруг точки (100, 200) на кадре 480x640


def _label_diff_pixels(label_scale: float) -> int:
    """Число пикселей, на которых кадр «с подписью» отличается от «без» (точка та же)."""
    black = np.zeros((480, 640, 3), dtype=np.uint8)
    with_label = _render(black, {"points": [{"xy": [100, 200], "label": _LABEL_TEXT}]}, label_scale=label_scale)
    without = _render(black, {"points": [{"xy": [100, 200]}]}, label_scale=label_scale)
    diff = (with_label != without).any(axis=2)
    return int(diff[_BAND].sum())


def test_default_scale_label_is_drawn():
    assert _label_diff_pixels(0.4) > 0  # предусловие: подпись на 0.4 вообще рисуется


def test_larger_label_scale_draws_more_pixels_than_smaller():
    small = _label_diff_pixels(0.4)
    large = _label_diff_pixels(1.2)

    assert large > small
    assert large >= 3 * small, f"подпись 1.2 даёт {large} px против {small} px на 0.4"


def test_label_scale_changes_label_pixels_not_only_marker():
    black = np.zeros((480, 640, 3), dtype=np.uint8)
    overlay = {"points": [{"xy": [100, 200], "label": _LABEL_TEXT}]}

    assert not np.array_equal(_render(black, overlay, label_scale=0.4), _render(black, overlay, label_scale=1.2))


# --------------------------------------------------------------------------
# Критерий 7: BGR-кадр без label_scale — пиксель в пиксель как до правки
# --------------------------------------------------------------------------

# Снято запуском текущего плагина (до правки) на входе ниже; конфиг пустой.
_LEGACY_SHA256 = "52b42f7450b64243e7133ae48452da4f2be57b7c6ba3b581f764530925b979fb"
_LEGACY_CHANGED_PIXELS = 18255


def _legacy_input() -> tuple[np.ndarray, dict]:
    frame = np.random.default_rng(12345).integers(0, 256, (480, 640, 3), dtype=np.uint8)
    overlay = {
        "lines": [
            {"p1": [50, 60], "p2": [600, 400]},
            {"p1": [10, 300], "p2": [500, 20], "color": [255, 0, 0], "thickness": 3},
        ],
        "dashed_lines": [{"p1": [20, 450], "p2": [620, 450]}],
        "vlines": [{"cx": 320, "cy": 240, "angle": 30, "zone_width": 80}],
        "points": [
            {"xy": [100, 100], "label": "QR-15MM"},
            {"xy": [200, 150], "label": "ok - 1 / 2", "color": [0, 255, 0]},
            {"xy": [300, 300]},
        ],
    }
    return frame, overlay


def test_bgr_frame_without_label_scale_is_pixel_identical_to_legacy():
    frame, overlay = _legacy_input()
    out = _render(frame, overlay)

    assert out.shape == (480, 640, 3)
    assert int((out != frame).any(axis=2).sum()) == _LEGACY_CHANGED_PIXELS
    assert hashlib.sha256(out.tobytes()).hexdigest() == _LEGACY_SHA256


def test_bgr_frame_with_default_label_scale_value_is_pixel_identical_to_legacy():
    """Явный label_scale=0.4 (умолчание из DESIGN) не меняет картинку относительно эталона."""
    frame, overlay = _legacy_input()
    out = _render(frame, overlay, label_scale=0.4)

    assert hashlib.sha256(out.tobytes()).hexdigest() == _LEGACY_SHA256
