"""Стиль по `group` из `color_table`: цвет, `scale` текста, приоритет per-shape над таблицей.

Универсальная часть механизма «цвета, текст и размеры надписей — из рецепта»: рисовальщик ничего не знает
о том, кто прислал фигуры, а стиль берёт из таблицы по `group`. Эталон — пиксели кадра, не внутренний API.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from Plugins.render.overlay_draw.plugin import OverlayDrawPlugin

_BLACK = np.zeros((200, 640, 3), dtype=np.uint8)
_TEXT = "QR-15MM test label"


def _render(overlay: dict, **cfg) -> np.ndarray:
    plugin = OverlayDrawPlugin()
    ctx = MagicMock()
    ctx.registers = None
    ctx.config = cfg
    ctx.log_info = MagicMock()
    plugin.configure(ctx)
    (out,) = plugin.process([{"frame": _BLACK, "overlay": overlay}])
    return out["frame"]


def _text_pixels(point: dict, table: list[dict]) -> int:
    """Число пикселей, которые подпись добавляет к той же точке без подписи."""
    with_label = _render({"points": [{**point, "label": _TEXT}]}, color_table=table)
    without = _render({"points": [point]}, color_table=table)
    return int((with_label != without).any(axis=2).sum())


def test_point_with_group_is_drawn_in_table_color():
    table = [{"group": "g", "color": [1, 2, 3]}]

    out = _render({"points": [{"xy": [50, 50], "group": "g"}]}, color_table=table)

    assert tuple(out[50, 50]) == (1, 2, 3)


def test_group_color_not_applied_to_other_group():
    table = [{"group": "g", "color": [1, 2, 3]}]

    out = _render({"points": [{"xy": [50, 50], "group": "other"}]}, color_table=table)

    assert tuple(out[50, 50]) != (1, 2, 3)


def test_line_group_color_and_thickness_from_table():
    table = [{"group": "frame_ok", "color": [0, 200, 0], "thickness": 5}]

    out = _render({"lines": [{"p1": [10, 100], "p2": [600, 100], "group": "frame_ok"}]}, color_table=table)

    assert tuple(out[100, 300]) == (0, 200, 0)
    assert tuple(out[102, 300]) == (0, 200, 0)  # толщина 5 из строки таблицы, не дефолтные 2


def test_scale_in_table_row_makes_text_larger():
    def pixels(scale: float) -> int:
        return _text_pixels({"xy": [20, 100], "group": "g"}, [{"group": "g", "color": [255, 255, 255], "scale": scale}])

    small, large = pixels(0.4), pixels(1.0)

    assert small > 0  # предусловие: подпись вообще рисуется
    assert large > 3 * small, f"scale 1.0 даёт {large} px против {small} px на 0.4"


def test_per_shape_scale_beats_table_scale():
    table = [{"group": "g", "color": [255, 255, 255], "scale": 0.4}]
    base = {"xy": [20, 100], "group": "g"}

    assert _text_pixels({**base, "scale": 1.0}, table) > 3 * _text_pixels(base, table)


def test_label_text_takes_group_color():
    table = [{"group": "g", "color": [0, 255, 0], "scale": 1.0}]
    point = {"xy": [20, 100], "group": "g"}
    with_label = _render({"points": [{**point, "label": _TEXT}]}, color_table=table)
    without = _render({"points": [point]}, color_table=table)

    changed = (with_label != without).any(axis=2)
    # на чёрном фоне зелёный текст — только канал G (антиалиасинг даёт оттенки, но не B и R)
    assert changed.sum() > 0
    assert int(with_label[changed][:, 0].max()) == 0 and int(with_label[changed][:, 2].max()) == 0
    assert int(with_label[changed][:, 1].max()) == 255


def test_per_shape_color_beats_table():
    table = [{"group": "g", "color": [1, 2, 3]}]

    out = _render({"points": [{"xy": [50, 50], "group": "g", "color": [9, 8, 7]}]}, color_table=table)

    assert tuple(out[50, 50]) == (9, 8, 7)
