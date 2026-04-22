# multiprocess_prototype/tests/test_schemas_pipeline.py
"""Тесты для канонических схем multiprocess_prototype.schemas (v3 pipeline)."""

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

from multiprocess_prototype.schemas.camera import HikvisionCameraRegisters, WebcamCameraRegisters
from multiprocess_prototype.schemas.pipeline import Pipeline


def test_schemas_pipeline_nested_structure():
    raw = {
        "cameras": {
            "cam_1": {
                "enabled": True,
                "registers": {"camera_type": "webcam", "resolution_width": 640, "resolution_height": 480},
                "regions": {
                    "full_frame": {
                        "rect": {"x": 0, "y": 0, "width": 640, "height": 480},
                        "processing_blocks": {
                            "color": {
                                "enabled": True,
                                "params": {
                                    "type": "color_detection",
                                    "color_lower": [0, 0, 150],
                                    "color_upper": [100, 100, 255],
                                    "min_area": 100,
                                    "max_area": 1000,
                                },
                            },
                            "blob": {
                                "enabled": False,
                                "params": {
                                    "type": "blob_detection",
                                    "threshold_step": 5,
                                    "min_area": 50,
                                },
                            },
                        },
                    }
                },
            }
        }
    }
    pipeline = Pipeline.model_validate(raw)
    out = pipeline.model_dump(mode="python")
    assert "cam_1" in out["cameras"]
    assert out["cameras"]["cam_1"]["regions"]["full_frame"]["processing_blocks"]["color"]["params"]["type"] == "color_detection"
    assert out["cameras"]["cam_1"]["regions"]["full_frame"]["processing_blocks"]["blob"]["params"]["type"] == "blob_detection"
    assert isinstance(pipeline.cameras["cam_1"].registers, WebcamCameraRegisters)


def test_schemas_pipeline_hikvision_registers():
    raw = {
        "cameras": {
            "cam_hk": {
                "registers": {
                    "camera_type": "hikvision",
                    "hikvision_resolution_width": 1920,
                    "hikvision_resolution_height": 1080,
                    "hikvision_exposure_time": 12000.0,
                },
                "regions": {},
            }
        }
    }
    pipeline = Pipeline.model_validate(raw)
    assert isinstance(pipeline.cameras["cam_hk"].registers, HikvisionCameraRegisters)
