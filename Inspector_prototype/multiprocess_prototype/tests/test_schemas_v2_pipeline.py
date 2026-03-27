# multiprocess_prototype/tests/test_schemas_v2_pipeline.py
"""Тесты schemas_v2.Pipeline: вложенность камеры → регионы → обработки."""
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

from multiprocess_prototype.registers.schemas_v2.camera import (
    HikvisionCameraRegisters,
    StandardCameraRegisters,
)
from multiprocess_prototype.registers.schemas_v2.pipeline import Pipeline, RegionNode
from multiprocess_prototype.registers.schemas_v2.processings.processing_block import ProcessingBlock
from multiprocess_prototype.registers.schemas_v2.processings.processing_params import (
    BlobDetectionParams,
    ColorDetectionParams,
)
from multiprocess_prototype.registers.schemas_v2.rect import Rect


def test_schemas_v2_pipeline_nested_roundtrip():
    raw = {
        "cameras": {
            "camera_0": {
                "enabled": True,
                "registers": {
                    "camera_type": "hikvision",
                    "hikvision_resolution_width": 1280,
                    "hikvision_resolution_height": 720,
                },
                "regions": {
                    "main": {
                        "rect": {"x": 100, "y": 100, "width": 400, "height": 300},
                        "enabled": True,
                        "processing_blocks": {
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
            "camera_1": {
                "enabled": False,
                "registers": {"camera_type": "webcam"},
                "regions": {},
            },
        }
    }
    cfg = Pipeline.model_validate(raw)
    out = cfg.model_dump(mode="python")
    assert out["cameras"]["camera_0"]["registers"]["camera_type"] == "hikvision"
    assert (
        out["cameras"]["camera_0"]["regions"]["main"]["processing_blocks"]["color_detector"]["params"][
            "type"
        ]
        == "color_detection"
    )
    assert (
        out["cameras"]["camera_0"]["regions"]["main"]["processing_blocks"]["blob_detector"]["params"][
            "type"
        ]
        == "blob_detection"
    )


def test_schemas_v2_runtime_add_helpers_and_full_frame():
    cfg = Pipeline()
    cfg.add_camera("cam_hk", HikvisionCameraRegisters())
    cfg.add_region("cam_hk", "roi_1", RegionNode(rect=Rect(x=10, y=20, width=100, height=80)))
    cfg.add_processing(
        "cam_hk",
        "roi_1",
        "color",
        ProcessingBlock(params=ColorDetectionParams()),
    )
    cfg.add_processing(
        "cam_hk",
        "roi_1",
        "blob",
        ProcessingBlock(enabled=False, params=BlobDetectionParams()),
    )

    assert "full_frame" in cfg.cameras["cam_hk"].regions
    assert "roi_1" in cfg.cameras["cam_hk"].regions
    assert cfg.cameras["cam_hk"].regions["full_frame"].rect.width == 1920
    assert cfg.cameras["cam_hk"].regions["full_frame"].rect.height == 1080
    assert cfg.cameras["cam_hk"].regions["roi_1"].processing_blocks["blob"].params.type == "blob_detection"


def test_schemas_v2_legacy_crop_regions_root_migration():
    raw = {"crop_regions": {"default": {"r1": [1, 2, 3, 4]}}}
    cfg = Pipeline.model_validate(raw)
    assert "default" in cfg.cameras
    assert cfg.cameras["default"].regions["r1"].rect.x == 1
    assert isinstance(cfg.cameras["default"].registers, StandardCameraRegisters)
    assert cfg.cameras["default"].regions["r1"].processing_blocks == {}
