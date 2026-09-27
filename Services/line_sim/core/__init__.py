"""Ядро line_sim: геометрия ленты, объект из слоёв, пресет сцены, фабрика объектов,
сцена (спавнер + фон)."""

from Services.line_sim.core.belt import BELT_UX, BELT_UY, FACTOR_MM, encoder_to_offset_mm
from Services.line_sim.core.factory import ObjectFactory
from Services.line_sim.core.layered_object import LayeredObject
from Services.line_sim.core.matching import BeltGeometry, JobDone, MatchResult, match_job, object_robot_xy
from Services.line_sim.core.preset import ScenePreset
from Services.line_sim.core.preview import (
    OUTSIDE_ROOTS_MESSAGE,
    PreviewLimitError,
    confine_preset_paths,
    render_preview_grid,
    validate_preview_request,
)
from Services.line_sim.core.scene_compositor import SceneCompositor
from Services.line_sim.core.spawner import ObjectSpawner
from Services.line_sim.core.truth import TruthLedger

__all__ = [
    "BELT_UX",
    "BELT_UY",
    "BeltGeometry",
    "FACTOR_MM",
    "JobDone",
    "LayeredObject",
    "MatchResult",
    "OUTSIDE_ROOTS_MESSAGE",
    "ObjectFactory",
    "ObjectSpawner",
    "PreviewLimitError",
    "SceneCompositor",
    "ScenePreset",
    "TruthLedger",
    "confine_preset_paths",
    "encoder_to_offset_mm",
    "match_job",
    "object_robot_xy",
    "render_preview_grid",
    "validate_preview_request",
]
