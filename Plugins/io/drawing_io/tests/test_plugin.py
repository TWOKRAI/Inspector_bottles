"""Тесты DrawingIoPlugin — armed-save, load-override, очистка загрузки."""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.io.drawing_io.plugin import DrawingIoPlugin


def _make_plugin(config: dict) -> DrawingIoPlugin:
    services = MockProcessServices(name="drawing_io", config=config)
    ctx = PluginContext(services=services, config=config)
    plugin = DrawingIoPlugin()
    plugin.configure(ctx)
    return plugin


def test_registered() -> None:
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    import Plugins.io.drawing_io.plugin  # noqa: F401

    entry = PluginRegistry.get("drawing_io")
    assert entry is not None
    assert entry.category == "io"


def test_save_armed_then_writes_on_next_frame(tmp_path) -> None:
    p = _make_plugin({"drawings_dir": str(tmp_path)})
    # Без arming — ничего не пишется.
    item = {"draw_points": [{"x_mm": 1.0, "y_mm": 2.0, "pen": 1}], "draw_bounds": [0, 0, 200, 200]}
    p.process([dict(item)])
    assert p._reg.saves_done == 0

    p.cmd_save({})
    p.process([dict(item)])
    assert p._reg.saves_done == 1
    assert p._reg.last_saved.endswith(".json")
    import os

    assert os.path.exists(p._reg.last_saved)


def test_save_includes_png_when_frame_present(tmp_path) -> None:
    p = _make_plugin({"drawings_dir": str(tmp_path), "save_image": True})
    frame = np.full((10, 10, 3), 200, dtype=np.uint8)
    p.cmd_save({})
    p.process([{"draw_points": [{"x_mm": 0.0, "y_mm": 0.0, "pen": 1}], "frame": frame}])
    import glob

    assert glob.glob(str(tmp_path / "*.png"))  # PNG записан рядом


def test_load_overrides_draw_points(tmp_path) -> None:
    p = _make_plugin({"drawings_dir": str(tmp_path)})
    # Сначала сохраним известный рисунок.
    saved = [{"x_mm": 5.0, "y_mm": 6.0, "pen": 0}, {"x_mm": 7.0, "y_mm": 8.0, "pen": 1}]
    p.cmd_save({})
    p.process([{"draw_points": saved, "draw_bounds": [0, 0, 100, 100]}])
    name = p._reg.last_saved

    # Загрузим и проверим подмену живых точек на загруженные.
    res = p.cmd_load({"path": name})
    assert res["status"] == "ok" and res["points"] == 2
    live = [{"x_mm": 99.0, "y_mm": 99.0, "pen": 1}]
    out = p.process([{"draw_points": live, "draw_bounds": [1, 1, 2, 2]}])[0]
    assert out["draw_points"] == saved  # живые заменены загруженными
    assert out["draw_bounds"] == [0.0, 0.0, 100.0, 100.0]


def test_load_empty_path_clears(tmp_path) -> None:
    p = _make_plugin({"drawings_dir": str(tmp_path)})
    p._loaded_points = [{"x_mm": 1.0, "y_mm": 1.0, "pen": 1}]
    p._reg.load_active = True
    res = p.cmd_load({"path": ""})
    assert res["load_active"] is False
    live = [{"x_mm": 99.0, "y_mm": 99.0, "pen": 1}]
    out = p.process([{"draw_points": live}])[0]
    assert out["draw_points"] == live  # вернулись к живым


def test_save_no_points_is_noop(tmp_path) -> None:
    p = _make_plugin({"drawings_dir": str(tmp_path)})
    p.cmd_save({})
    p.process([{"frame": np.zeros((4, 4, 3), dtype=np.uint8)}])  # нет draw_points
    assert p._reg.saves_done == 0
