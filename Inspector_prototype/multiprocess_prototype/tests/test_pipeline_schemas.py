# multiprocess_prototype/tests/test_pipeline_schemas.py
"""Иерархия PipelineConfig: дискриминатор, YAML-подобный dict, миграция crop_regions."""
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

from multiprocess_prototype.registers.schemas.pipeline import PipelineConfig


def test_pipeline_yaml_discriminated_union_roundtrip():
    raw = {
        "cameras": {
            "camera_0": {
                "enabled": True,
                "regions": {
                    "main": {
                        "rect": {"x": 100, "y": 100, "width": 400, "height": 300},
                        "enabled": True,
                        "processing": {
                            "color_detector": {
                                "enabled": True,
                                "params": {
                                    "type": "color_detection",
                                    "color_lower": [0, 0, 150],
                                    "color_upper": [100, 100, 255],
                                    "min_area": 500,
                                    "max_area": 50000,
                                },
                            },
                            "blob_detector": {
                                "enabled": False,
                                "params": {
                                    "type": "blob_detection",
                                    "threshold_step": 10,
                                    "min_area": 200,
                                },
                            },
                        },
                    },
                },
            },
            "camera_1": {"enabled": False, "regions": {}},
        }
    }
    cfg = PipelineConfig.model_validate(raw)
    out = cfg.model_dump(mode="python")
    assert out["cameras"]["camera_0"]["regions"]["main"]["processing"]["color_detector"]["params"][
        "type"
    ] == "color_detection"


def test_pipeline_legacy_crop_regions_root():
    raw = {"crop_regions": {"default": {"r1": [1, 2, 3, 4]}}}
    cfg = PipelineConfig.model_validate(raw)
    assert "default" in cfg.cameras
    assert cfg.cameras["default"].regions["r1"].rect.x == 1
