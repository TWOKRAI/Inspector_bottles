"""Тесты HsvMaskPlugin — маска по HSV, кадр сохраняется."""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.hsv_mask.plugin import HsvMaskPlugin


def _make_plugin(config: dict | None = None) -> HsvMaskPlugin:
    services = MockProcessServices(name="hsv_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = HsvMaskPlugin()
    plugin.configure(ctx)
    return plugin


def _red_square_frame() -> np.ndarray:
    """Кадр 100x100 BGR с красным квадратом 40x40 в центре (остальное чёрное)."""
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[30:70, 30:70] = (0, 0, 255)  # BGR красный
    return frame


def test_keeps_original_frame_adds_mask() -> None:
    plugin = _make_plugin()
    frame = _red_square_frame()
    out = plugin.process([{"frame": frame, "frame_id": 1}])[0]
    # Кадр НЕ изменён (тот же объект-данные)
    assert np.array_equal(out["frame"], frame)
    # Маска добавлена, бинарная uint8
    assert "mask" in out
    assert out["mask"].dtype == np.uint8
    assert out["mask"].shape == (100, 100)


def test_mask_selects_red_region() -> None:
    # Красный в HSV OpenCV ≈ H 0..10 или 170..179; берём широкий диапазон по красному
    plugin = _make_plugin({"h_min": 0, "h_max": 10, "s_min": 100, "v_min": 100})
    frame = _red_square_frame()
    mask = plugin.process([{"frame": frame}])[0]["mask"]
    # Внутри квадрата маска белая, снаружи чёрная
    assert mask[50, 50] == 255
    assert mask[5, 5] == 0
    # Площадь белого ≈ 40*40
    assert 1400 <= int(np.count_nonzero(mask)) <= 1700


def test_empty_when_color_absent() -> None:
    plugin = _make_plugin({"h_min": 60, "h_max": 80, "s_min": 100, "v_min": 100})  # зелёный
    frame = _red_square_frame()
    mask = plugin.process([{"frame": frame}])[0]["mask"]
    assert int(np.count_nonzero(mask)) == 0


def test_none_frame_skipped() -> None:
    plugin = _make_plugin()
    assert plugin.process([{"frame": None}]) == []


def _hue_square_frame(hue: int) -> np.ndarray:
    """Кадр 100x100 BGR с квадратом 40x40 заданного Hue (S=V=255), фон чёрный."""
    hsv = np.zeros((100, 100, 3), dtype=np.uint8)
    hsv[30:70, 30:70] = (hue, 255, 255)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_wrap_around_catches_high_hue() -> None:
    """h_min>h_max → wrap-around: верхняя полоса [170..179] ловит красный H≈175."""
    frame = _hue_square_frame(175)
    wrap = _make_plugin({"h_min": 170, "h_max": 10, "s_min": 100, "v_min": 100})
    mask_wrap = wrap.process([{"frame": frame}])[0]["mask"]
    assert mask_wrap[50, 50] == 255
    assert mask_wrap[5, 5] == 0
    # Одиночный диапазон [0..10] такой Hue НЕ ловит — доказывает необходимость wrap.
    single = _make_plugin({"h_min": 0, "h_max": 10, "s_min": 100, "v_min": 100})
    mask_single = single.process([{"frame": frame}])[0]["mask"]
    assert int(np.count_nonzero(mask_single)) == 0


def test_wrap_around_catches_both_red_bands() -> None:
    """Wrap-диапазон ловит и низкий (H≈2), и высокий (H≈177) красный одновременно."""
    plugin = _make_plugin({"h_min": 170, "h_max": 10, "s_min": 100, "v_min": 100})
    for hue in (2, 177):
        mask = plugin.process([{"frame": _hue_square_frame(hue)}])[0]["mask"]
        assert mask[50, 50] == 255, f"Hue {hue} не пойман wrap-диапазоном"
