"""Тесты CropPlugin — обрезка кадра по [x,y,w,h] + resize к выходному размеру."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.crop.plugin import CropPlugin


def _make_plugin(config: dict | None = None) -> CropPlugin:
    services = MockProcessServices(name="crop", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = CropPlugin()
    plugin.configure(ctx)
    return plugin


def _frame(h: int = 480, w: int = 640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_registered() -> None:
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    import Plugins.processing.crop.plugin  # noqa: F401

    entry = PluginRegistry.get("crop")
    assert entry is not None
    assert entry.category == "processing"


def test_passthrough_when_all_zero() -> None:
    p = _make_plugin()
    f = _frame()
    out = p.process([{"frame": f}])[0]
    assert out["frame"] is f  # тот же объект — без изменений


def test_crop_region_resized_back_to_source_size() -> None:
    # Регион 320x240 без out → ресайз обратно к 640x480 (размерности тракта стабильны).
    p = _make_plugin({"crop_x": 100, "crop_y": 50, "crop_w": 320, "crop_h": 240})
    out = p.process([{"frame": _frame(480, 640)}])[0]
    assert out["frame"].shape == (480, 640, 3)
    assert p._reg.last_w == 320 and p._reg.last_h == 240


def test_crop_to_explicit_out_size() -> None:
    p = _make_plugin({"crop_x": 0, "crop_y": 0, "crop_w": 200, "crop_h": 200, "out_width": 100, "out_height": 100})
    out = p.process([{"frame": _frame(480, 640)}])[0]
    assert out["frame"].shape == (100, 100, 3)


def test_crop_w_zero_means_to_edge() -> None:
    # crop_w=0 → до правого края (640-x).
    p = _make_plugin({"crop_x": 40, "crop_w": 0, "crop_h": 0, "out_width": 0, "out_height": 0})
    out = p.process([{"frame": _frame(480, 640)}])[0]
    assert p._reg.last_w == 600  # 640 - 40
    assert p._reg.last_h == 480
    assert out["frame"].shape == (480, 640, 3)  # ресайз обратно к исходному


def test_no_frame_passthrough() -> None:
    p = _make_plugin({"crop_w": 100})
    item = {"meta": 1}
    assert p.process([item])[0] == item


# --- clip-режим: обрезка без масштаба + сдвиг + отсечение за краем ---


def test_clip_keeps_native_scale_no_resize() -> None:
    # Регион 200x100 в clip-режиме на холст 640x480 — БЕЗ растяжения (нативный размер).
    f = _frame(480, 640)
    f[:] = 0
    f[50:150, 100:300] = 200  # яркий прямоугольник 200(w)x100(h) в источнике
    p = _make_plugin({"mode": "clip", "crop_x": 100, "crop_y": 50, "crop_w": 200, "crop_h": 100})
    out = p.process([{"frame": f}])[0]["frame"]
    assert out.shape == (480, 640, 3)  # холст стабилен
    # Регион лёг в (0,0) нативно: 200x100 яркого, остальное белый фон (255).
    assert (out[0:100, 0:200] == 200).all()
    assert (out[200, 400] == 255).all()  # вне региона — белый холст


def test_clip_paste_offset_moves_region() -> None:
    f = _frame(480, 640)
    f[:] = 30
    p = _make_plugin(
        {"mode": "clip", "crop_x": 0, "crop_y": 0, "crop_w": 100, "crop_h": 100, "paste_x": 50, "paste_y": 60}
    )
    out = p.process([{"frame": f}])[0]["frame"]
    assert (out[0, 0] == 255).all()  # до сдвига — белый фон
    assert (out[60, 50] == 30).all()  # регион сдвинут на (50,60)


def test_clip_truncates_at_canvas_edge() -> None:
    # Регион уезжает за правый/нижний край — отсекается (не падает, не ресайзится).
    f = _frame(480, 640)
    f[:] = 77
    p = _make_plugin(
        {
            "mode": "clip",
            "crop_w": 200,
            "crop_h": 200,
            "out_width": 100,
            "out_height": 100,
            "paste_x": 50,
            "paste_y": 50,
        }
    )
    out = p.process([{"frame": f}])[0]["frame"]
    assert out.shape == (100, 100, 3)  # холст 100x100
    assert (out[50, 50] == 77).all()  # видимая часть региона
    assert (out[10, 10] == 255).all()  # до сдвига — фон
