"""Ядро line_sim: геометрия ленты, объект из слоёв, пресет сцены, фабрика объектов,
сцена (спавнер + фон)."""

from Services.line_sim.core.belt import BELT_UX, BELT_UY, FACTOR_MM, encoder_to_offset_mm
from Services.line_sim.core.factory import ObjectFactory
from Services.line_sim.core.layered_object import LayeredObject
from Services.line_sim.core.matching import BeltGeometry, JobDone, MatchResult, match_job, object_robot_xy
from Services.line_sim.core.preset import (
    REPO_ROOT,
    ScenePreset,
    apply_defect_override,
    load_scene_preset,
    resolve_repo_path,
)
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
    "REPO_ROOT",
    "SceneCompositor",
    "ScenePreset",
    "TruthLedger",
    "apply_defect_override",
    "confine_preset_paths",
    "encoder_to_offset_mm",
    "load_scene_preset",
    "match_job",
    "object_robot_xy",
    "render_preview_grid",
    "resolve_repo_path",
    "validate_preview_request",
]
