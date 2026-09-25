"""Авторские тесты ``InspectorRecipeFormatHook`` (Task 1b.1, фикс-раунд ревью).

Что может сломаться: ``to_topology`` развернёт рецепт (``unwrap_recipe``) и срежет
top-level ``devices:`` — хаб извлекает устройства из тела, пришедшего в
``topology.apply`` (``orchestrator_hooks``, S-25), и пересобранный ``devices``
поднимется с пустым хабом. Сегодня это замаскировано ``protected: true``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook
from multiprocess_prototype.recipes.devices_sync import extract_recipe_devices

_RECIPES = sorted((Path(__file__).resolve().parents[2] / "recipes").glob("*.yaml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", _RECIPES, ids=lambda p: p.stem)
def test_to_topology_keeps_recipe_devices(path: Path) -> None:
    hook = InspectorRecipeFormatHook()
    raw = _load(path)
    assert extract_recipe_devices(hook.to_topology(hook.normalize(raw))) == extract_recipe_devices(raw)


def test_letter_robot_sim_devices_literal() -> None:
    hook = InspectorRecipeFormatHook()
    raw = _load(next(p for p in _RECIPES if p.stem == "letter_robot_sim"))
    got = extract_recipe_devices(hook.to_topology(hook.normalize(raw)))
    assert [(d["id"], d["kind"]) for d in got] == [("robot_main", "robot"), ("vfd_belt", "vfd")]


def test_recipes_dir_is_not_empty() -> None:
    assert len(_RECIPES) >= 10  # параметризация выше не должна стать пустой молча
