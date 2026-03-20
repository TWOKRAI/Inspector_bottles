# multiprocess_prototype/tests/test_processor_register_update.py
"""Обработка register_update: register_sync-модули (без запуска процесса)."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_paths() -> None:
    proto = Path(__file__).resolve().parent.parent
    root = proto.parent
    mods = root / "multiprocess_framework" / "refactored" / "modules"
    for p in (str(root), str(mods)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_paths()

from multiprocess_prototype.backend.modules.processor_frame.detection import ColorBlobDetector
from multiprocess_prototype.backend.modules.processor_frame.register_sync import (
    apply_processor_register_update,
)
from multiprocess_prototype.backend.modules.renderer.register_sync import (
    apply_renderer_register_update,
)


def test_processor_apply_register_update_color_lower():
    det = ColorBlobDetector([0, 0, 150], [100, 100, 255], 500, 50000)

    def set_color_range(d):
        det.apply_color_range(d.get("color_lower"), d.get("color_upper"))

    def set_min_area(d):
        det.set_min_area(d.get("min_area", det.min_area))

    def set_max_area(d):
        det.set_max_area(d.get("max_area", det.max_area))

    apply_processor_register_update(
        {"register_name": "processor", "field_name": "color_lower", "value": [1, 2, 3]},
        set_color_range=set_color_range,
        set_min_area=set_min_area,
        set_max_area=set_max_area,
    )
    assert det.color_lower.tolist() == [1, 2, 3]
    assert det.color_upper.tolist() == [100, 100, 255]


def test_processor_apply_register_update_ignores_foreign_register():
    det = ColorBlobDetector([0, 0, 150], [100, 100, 255], 500, 50000)

    def set_color_range(d):
        det.apply_color_range(d.get("color_lower"), d.get("color_upper"))

    def set_min_area(d):
        det.set_min_area(d.get("min_area", det.min_area))

    def set_max_area(d):
        det.set_max_area(d.get("max_area", det.max_area))

    apply_processor_register_update(
        {"register_name": "renderer", "field_name": "show_mask", "value": False},
        set_color_range=set_color_range,
        set_min_area=set_min_area,
        set_max_area=set_max_area,
    )
    assert det.color_lower.tolist() == [0, 0, 150]


def test_renderer_apply_register_update_show_mask():
    state = {
        "show_original": True,
        "show_mask": True,
        "draw_contours": True,
        "draw_bboxes": True,
        "save_frames": False,
    }

    def set_draw_contours(d):
        state["draw_contours"] = bool(d.get("draw_contours", state["draw_contours"]))

    def set_show_original(d):
        state["show_original"] = bool(d.get("show_original", state["show_original"]))

    def set_show_mask(d):
        state["show_mask"] = bool(d.get("show_mask", state["show_mask"]))

    def set_draw_bboxes(d):
        state["draw_bboxes"] = bool(d.get("draw_bboxes", state["draw_bboxes"]))

    def set_save_frames(d):
        state["save_frames"] = bool(d.get("save_frames", state["save_frames"]))

    apply_renderer_register_update(
        {"register_name": "renderer", "field_name": "show_mask", "value": False},
        set_draw_contours=set_draw_contours,
        set_show_original=set_show_original,
        set_show_mask=set_show_mask,
        set_draw_bboxes=set_draw_bboxes,
        set_save_frames=set_save_frames,
    )
    assert state["show_mask"] is False
    assert state["show_original"] is True
