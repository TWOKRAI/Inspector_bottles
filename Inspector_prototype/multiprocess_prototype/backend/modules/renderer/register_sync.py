"""register_update для RendererRegisters — имена полей как в registers/schemas."""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_prototype.registers.schemas.processing_tab.names import (
    RENDERER_REGISTER,
)


def apply_renderer_register_update(
    data: dict,
    *,
    set_draw_contours: Callable[[dict], Any],
    set_show_original: Callable[[dict], Any],
    set_show_mask: Callable[[dict], Any],
    set_draw_bboxes: Callable[[dict], Any],
    set_save_frames: Callable[[dict], Any],
) -> None:
    if data.get("register_name") != RENDERER_REGISTER:
        return
    field = data.get("field_name")
    value = data.get("value")
    if field == "show_original":
        set_show_original({"show_original": value})
    elif field == "show_mask":
        set_show_mask({"show_mask": value})
    elif field == "draw_contours":
        set_draw_contours({"draw_contours": value})
    elif field == "draw_bboxes":
        set_draw_bboxes({"draw_bboxes": value})
    elif field == "save_frames":
        set_save_frames({"save_frames": value})
