# -*- coding: utf-8 -*-
"""Канонические схемы пайплайна (v3): Pipeline → CameraNode → Region → ProcessingBlock."""

from .camera import BaseCameraRegisters, HikvisionCameraRegisters, WebcamCameraRegisters
from .pipeline import CameraNode, Pipeline, RegionNode

__all__ = [
    "Pipeline",
    "CameraNode",
    "BaseCameraRegisters",
    "WebcamCameraRegisters",
    "HikvisionCameraRegisters",
    "RegionNode",
]
