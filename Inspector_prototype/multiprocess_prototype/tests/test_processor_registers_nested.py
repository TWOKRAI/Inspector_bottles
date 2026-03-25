# multiprocess_prototype/tests/test_processor_registers_nested.py
"""ProcessorRegisters: нормализация crop_regions / post_processing_regions при validate."""

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

from multiprocess_prototype.registers.schemas.processing_tab import ProcessorRegisters


def test_processor_validates_legacy_flat_crop_regions():
    p = ProcessorRegisters.model_validate(
        {
            "crop_regions": {
                "r1": {
                    "params": {"x_min": 0, "x_max": 10, "height": 3, "y_delta": 1},
                    "rect": {},
                }
            },
        }
    )
    assert "default" in p.crop_regions
    assert p.crop_regions["default"]["r1"] == [0, 1, 10, 3]


def test_processor_post_processing_normalizes():
    p = ProcessorRegisters.model_validate(
        {
            "post_processing_regions": {
                "cam1": [{"name": "a", "x1": 0, "y1": 0, "x2": 1, "y2": 2}],
            },
        }
    )
    assert p.post_processing_regions["cam1"][0]["name"] == "a"


def test_create_registers_loads_legacy_recipe_snapshot():
    from multiprocess_prototype.registers import create_registers

    registers, _ = create_registers()
    snap = registers.model_dump_all()
    snap["processor"]["crop_regions"] = {
        "legacy": {
            "params": {"x_min": 0, "x_max": 5, "height": 2, "y_delta": 0},
            "rect": {},
        }
    }
    registers.model_validate_all(snap, strict=False)
    reg = registers.get_register("processor")
    assert reg is not None
    assert "default" in reg.crop_regions
    assert reg.crop_regions["default"]["legacy"] == [0, 0, 5, 2]
