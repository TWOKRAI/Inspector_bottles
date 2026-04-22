# multiprocess_prototype/tests/test_logical_cameras.py
"""Координатор логических камер и ProcessorRegisters.logical_camera_ids."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_paths() -> None:
    proto = Path(__file__).resolve().parent.parent
    root = proto.parent
    mods = root / "multiprocess_framework" / "modules"
    for p in (str(root), str(proto), str(mods)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_paths()

from multiprocess_prototype.frontend.coordinators.logical_cameras import (
    compute_logical_camera_id,
    ensure_logical_camera_and_seed_roi,
)
from multiprocess_prototype.registers import create_registers
from multiprocess_prototype.registers.schemas.pipeline.widget_bridge import crop_nested_from_pipeline
from multiprocess_prototype.registers.schemas.processing_tab.names import PROCESSOR_REGISTER


def test_compute_logical_camera_id():
    assert compute_logical_camera_id("simulator") == "simulator"
    assert compute_logical_camera_id("webcam", device_id=1) == "webcam_1"
    assert compute_logical_camera_id("hikvision", camera_index=2) == "hikvision_2"


def test_ensure_seeds_ids_and_full_roi():
    registers, _ = create_registers()
    cam = registers.get_register("camera")
    cam.camera_type = "webcam"
    cam.device_id = 0
    cam.resolution_width = 800
    cam.resolution_height = 600

    ensure_logical_camera_and_seed_roi(registers)

    proc = registers.get_register(PROCESSOR_REGISTER)
    assert "webcam_0" in proc.logical_camera_ids
    nested = crop_nested_from_pipeline(proc.vision_pipeline)
    assert nested["webcam_0"]["full"] == [0, 0, 800, 600]


def test_processor_registers_has_logical_camera_ids_field():
    from multiprocess_prototype.registers.schemas.processing_tab import ProcessorRegisters

    p = ProcessorRegisters()
    assert p.logical_camera_ids == []


def test_logical_camera_ids_set_does_not_invoke_send_callback():
    """FieldMeta process_targets [] — нет register_update на процессы (ADR-094)."""
    channels: list[str] = []

    def send_cb(channel: str, *args: object) -> None:
        channels.append(channel)

    registers, _ = create_registers()
    registers.set_send_callback(send_cb)
    registers.set_field_value(PROCESSOR_REGISTER, "logical_camera_ids", ["simulator"])
    assert channels == []
