"""Конвертеры между двухслойной моделью (SourceTopology + ProcessingConfig) и legacy Pipeline.

Обеспечивает обратную совместимость: ProcessorService пока читает Pipeline,
конвертер собирает его из двух слоёв.
"""

from __future__ import annotations

from typing import Any, Dict

from ..camera.schemas import BaseCameraRegisters
from ..pipeline.processing_node import ProcessingNode
from ..pipeline.rect import Rect
from ..pipeline.schemas import CameraNode, Pipeline, RegionNode
from ..processor.processings.base import BaseProcessingBlock
from .schemas import (
    CameraSourceConfig,
    RegionSourceConfig,
    ShmSlotConfig,
    SourceTopology,
)

# Импорт Layer 2 — ленивый, чтобы не создавать циклических зависимостей
# при импорте только Layer 1
_ProcessingConfig = None
_RegionPipelineConfig = None


def _ensure_processing_imports() -> None:
    global _ProcessingConfig, _RegionPipelineConfig
    if _ProcessingConfig is None:
        from ..processing.schemas import ProcessingConfig, RegionPipelineConfig
        _ProcessingConfig = ProcessingConfig
        _RegionPipelineConfig = RegionPipelineConfig


def layers_to_pipeline(
    topology: SourceTopology,
    processing: Any,
) -> Pipeline:
    """Собрать legacy Pipeline из двух слоёв (Layer 1 + Layer 2).

    Args:
        topology: SourceTopology (Layer 1) — камеры и регионы.
        processing: ProcessingConfig (Layer 2) — processing nodes по регионам.

    Returns:
        Pipeline — legacy-совместимая структура для ProcessorService.
    """
    cameras: Dict[str, CameraNode] = {}

    for cam_key, cam_cfg in topology.cameras.items():
        # Регионы этой камеры
        cam_regions = topology.regions_for_camera(cam_key)
        regions: Dict[str, RegionNode] = {}

        for reg_key, reg_cfg in cam_regions.items():
            rect = reg_cfg.rect

            # Processing nodes из Layer 2
            nodes: Dict[str, ProcessingNode] = {}
            if processing is not None:
                pipelines = getattr(processing, "region_pipelines", {})
                rp = pipelines.get(reg_key)
                if rp is not None:
                    nodes = dict(getattr(rp, "nodes", {}))

            regions[reg_key] = RegionNode(
                rect=rect,
                enabled=reg_cfg.enabled,
                is_main=reg_cfg.is_main,
                processing_enabled=reg_cfg.processing_enabled,
                sort_order=reg_cfg.sort_order,
                nodes=nodes,
            )

        cameras[cam_key] = CameraNode(
            enabled=True,
            registers=cam_cfg.registers,
            regions=regions,
        )

    return Pipeline(cameras=cameras)


def pipeline_to_layers(
    pipeline: Pipeline,
) -> tuple[SourceTopology, Any]:
    """Мигрировать legacy Pipeline в двухслойную модель.

    Args:
        pipeline: Pipeline — legacy-структура.

    Returns:
        (SourceTopology, ProcessingConfig) — два слоя.
    """
    _ensure_processing_imports()

    cameras: Dict[str, CameraSourceConfig] = {}
    regions: Dict[str, RegionSourceConfig] = {}
    region_pipelines: Dict[str, Any] = {}

    for cam_key, cam_node in pipeline.cameras.items():
        # Извлечь camera_id из ключа
        cam_id = 0
        if "_" in cam_key:
            try:
                cam_id = int(cam_key.split("_")[-1])
            except ValueError:
                pass

        regs = cam_node.registers
        cam_type = getattr(regs, "camera_type", "simulator")
        res_w = getattr(regs, "resolution_width", 640)
        res_h = getattr(regs, "resolution_height", 480)

        cameras[cam_key] = CameraSourceConfig(
            camera_id=cam_id,
            camera_type=cam_type,
            registers=regs,
            shm_config=ShmSlotConfig(
                name=f"camera_{cam_id}_frame",
                width=res_w,
                height=res_h,
                channels=3,
            ),
        )

        # Регионы
        for reg_key, reg_node in cam_node.regions.items():
            rect = getattr(reg_node, "rect", Rect())
            regions[reg_key] = RegionSourceConfig(
                camera_ref=cam_key,
                rect=rect,
                enabled=reg_node.enabled,
                is_main=reg_node.is_main,
                processing_enabled=reg_node.processing_enabled,
                sort_order=getattr(reg_node, "sort_order", 0),
            )

            # Processing nodes → Layer 2
            nodes = dict(getattr(reg_node, "nodes", {}))
            if nodes:
                region_pipelines[reg_key] = _RegionPipelineConfig(
                    enabled=True,
                    nodes=nodes,
                )

    topology = SourceTopology(cameras=cameras, regions=regions)
    processing = _ProcessingConfig(region_pipelines=region_pipelines)
    return topology, processing


__all__ = [
    "layers_to_pipeline",
    "pipeline_to_layers",
]
