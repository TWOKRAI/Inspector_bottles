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


def test_main_applies_env_aliases_before_resolve(monkeypatch, tmp_path) -> None:
    """MAJOR-3 регресс: при заданном ТОЛЬКО MULTIPROCESS_MANIFEST main() собирает spec
    на кастомном app.yaml (env-алиас применён ДО resolve_manifest_path/persist).

    Без раннего apply_env_aliases resolve_manifest_path (читает лишь INSPECTOR_MANIFEST)
    вернул бы дефолт → backend и GUI разошлись бы по манифестам (split-brain).
    """
    import multiprocess_prototype.main as main_mod

    custom = tmp_path / "custom_app.yaml"
    custom.write_text("name: Custom\npipeline: p.yaml\n", encoding="utf-8")

    # Задан только каноничный ключ; легаси-ключ отсутствует (tracked → восстановится).
    monkeypatch.delenv("INSPECTOR_MANIFEST", raising=False)
    monkeypatch.setenv("MULTIPROCESS_MANIFEST", str(custom))

    captured: dict = {}

    def fake_run_app(spec) -> int:
        captured["manifest_path"] = spec.manifest_path
        return 0

    # main() делает локальный `from ...app_module import run_app` — патчим атрибут пакета.
    monkeypatch.setattr("multiprocess_framework.modules.app_module.run_app", fake_run_app)

    assert main_mod.main() == 0
    assert Path(captured["manifest_path"]) == custom
