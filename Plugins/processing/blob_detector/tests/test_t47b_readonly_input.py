# -*- coding: utf-8 -*-
"""Task 4.7b — blob_detector на read-only входе (zero-copy view из SHM пайплайна).

Предохранитель-«сохранение»: после 4.7b читатель-пайплайн отдаёт кадр с ``writeable == False``.
Контракт: ``draw_contours=True`` на таком кадре НЕ падает (``ValueError: assignment destination is
read-only``), контуры рисуются на копии, входные байты не меняются. На момент написания, вероятно,
уже ЗЕЛЁНЫЙ (T1 копирует кадр перед рисованием) — тест держит это при смене режима чтения.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from Plugins.processing.blob_detector.plugin import BlobDetectorPlugin


def _readonly_frame() -> np.ndarray:
    """200x200 BGR, белый квадрат 60..140; массив только для чтения и не владеет данными (как view)."""
    buf = np.zeros((200, 200, 3), np.uint8)
    buf[60:140, 60:140] = 255
    arr = np.frombuffer(buf.tobytes(), dtype=np.uint8).reshape(200, 200, 3)
    assert not arr.flags.writeable and not arr.flags.owndata
    return arr


def test_draw_contours_on_readonly_input_works_and_input_unchanged() -> None:
    ctx = MagicMock()
    ctx.config = {
        "h_min": 0,
        "h_max": 180,
        "s_min": 0,
        "s_max": 255,
        "v_min": 200,
        "v_max": 255,
        "min_area": 10,
        "max_area": 0,
        "draw_contours": True,
        "contour_color_bgr": [0, 0, 255],
        "contour_thickness": 1,
    }
    plugin = BlobDetectorPlugin()
    plugin.configure(ctx)
    frame = _readonly_frame()
    before = frame.tobytes()

    result = plugin.process([{"frame": frame}])

    assert len(result) == 1, "item потерян на read-only входе"
    assert len(result[0]["detections"]) == 1, "белый квадрат должен дать ровно одну детекцию"
    assert frame.tobytes() == before, "входной кадр изменён"
    assert not frame.flags.writeable, "вход должен остаться read-only"
    out = result[0]["frame"]
    assert out is not frame and out.flags.writeable, "выход должен быть независимой записываемой копией"
    red = (out[..., 0] == 0) & (out[..., 1] == 0) & (out[..., 2] == 255)
    assert int(red.sum()) > 0, "контур не нарисован на выходном кадре"
