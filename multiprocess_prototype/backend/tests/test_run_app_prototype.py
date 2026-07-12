"""Оба живых рецепта бутятся через app_module.run_app (Ф5.11 acceptance).

Полный headless-бут hardware-рецептов (phone/hikvision) невозможен без железа
([[hardware-recipes-no-headless-boot]]) — как и снапшот 5.1, проверяем на уровне
СБОРКИ: путь через ``build_app(AppSpec factory)`` даёт тот же launcher (имена/число
процессов + orchestrator_class_path), что прямой ``SystemBuilder.build()``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RECIPES = ["phone_sketch", "hikvision_letter_robot"]


def _direct_build(recipe: str):
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    return SystemBuilder.from_manifest(app, recipe).build()


def _via_run_app(recipe: str):
    from multiprocess_framework.modules.app_module import AppSpec, build_app
    from multiprocess_prototype.main import _prototype_launcher_factory

    spec = AppSpec(
        manifest_path=PROJECT_ROOT / "multiprocess_prototype" / "app.yaml",
        pipeline_override=recipe,
        launcher_factory=_prototype_launcher_factory,
    )
    return build_app(spec)


@pytest.mark.parametrize("recipe", RECIPES)
def test_recipe_boots_via_run_app_matches_direct(recipe: str) -> None:
    direct = _direct_build(recipe)
    via = _via_run_app(recipe)

    assert [n for n, _ in via._processes] == [n for n, _ in direct._processes]
    assert via._orchestrator_class_path == direct._orchestrator_class_path
    assert via._orchestrator_class_path == ("multiprocess_prototype.orchestrator.ProcessManagerProcessApp")
