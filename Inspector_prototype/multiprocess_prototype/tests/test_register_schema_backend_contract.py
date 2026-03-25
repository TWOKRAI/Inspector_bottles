# multiprocess_prototype/tests/test_register_schema_backend_contract.py
"""
Согласованность полей регистров с ветками _apply_register_update в процессах.

При добавлении поля в ProcessorRegisters / RendererRegisters нужно обработать его
в `modules/processor_frame/register_sync.py` и `modules/renderer/register_sync.py` (и наоборот).
"""
from __future__ import annotations

import sys
from pathlib import Path


def _paths() -> None:
    proto = Path(__file__).resolve().parent.parent
    root = proto.parent
    mods = root / "multiprocess_framework" / "refactored" / "modules"
    for p in (str(root), str(proto), str(mods)):
        if p not in sys.path:
            sys.path.insert(0, p)


_paths()

from multiprocess_prototype.registers.schemas.camera_tab import CameraRegisters
from multiprocess_prototype.registers.schemas.processing_tab import (
    ProcessorRegisters,
    RendererRegisters,
)

# Должно совпадать с modules/camera/register_sync.py
_CAMERA_FIELDS = frozenset(
    {
        "camera_type",
        "fps",
        "resolution_width",
        "resolution_height",
        "device_id",
        "camera_index",
        "hikvision_resolution_width",
        "hikvision_resolution_height",
        "hikvision_frame_rate",
        "hikvision_exposure_time",
        "hikvision_gain",
    }
)
# Поля ProcessorRegisters; обработка в processor_frame/register_sync.py — пока color/min_area/max_area;
# crop_regions / post_processing_regions — снимок для GUI/рецепта (бэкенд может игнорировать до фазы 2).
_PROCESSOR_FIELDS = frozenset(
    {
        "color_lower",
        "color_upper",
        "min_area",
        "max_area",
        "crop_regions",
        "post_processing_regions",
        "logical_camera_ids",
    }
)
# Должно совпадать с modules/renderer/register_sync.py
_RENDERER_FIELDS = frozenset(
    {"show_original", "show_mask", "draw_contours", "draw_bboxes", "save_frames"}
)


def test_camera_registers_fields_match_backend_handler():
    assert set(CameraRegisters.model_fields) == _CAMERA_FIELDS


def test_processor_registers_fields_match_backend_handler():
    assert set(ProcessorRegisters.model_fields) == _PROCESSOR_FIELDS


def test_renderer_registers_fields_match_backend_handler():
    assert set(RendererRegisters.model_fields) == _RENDERER_FIELDS
