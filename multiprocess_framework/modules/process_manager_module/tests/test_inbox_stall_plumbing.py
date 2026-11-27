# -*- coding: utf-8 -*-
"""Task 2.2e (REDS 11) — ключ ``inbox_stall_s``: рецепт -> blueprint -> proc_dict и пин рецептов букв."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import ProcessConfig

_RECIPES = Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "recipes"
_WATCHED = ("vision", "line", "recog", "layout")


def _built_config(extras: dict) -> dict:
    launch = ProcessConfig(process_name="recog", plugins=[], extras=extras).as_generic_config()
    return launch.build()[1]["config"]


def test_inbox_stall_plumbing() -> None:
    assert _built_config({"inbox_stall_s": 15.0})["inbox_stall_s"] == 15.0
    assert _built_config({"inbox_stall_s": "abc"})["inbox_stall_s"] == "abc"
    assert "inbox_stall_s" not in _built_config({})


@pytest.mark.parametrize("recipe", ["hikvision_letter_robot.yaml", "letter_robot_sim.yaml"])
def test_recipe_pin(recipe: str) -> None:
    data = yaml.safe_load((_RECIPES / recipe).read_text(encoding="utf-8"))
    by_name = {p["process_name"]: p for p in data["blueprint"]["processes"]}
    assert set(_WATCHED) <= set(by_name)
    for name, process in by_name.items():
        extras = process.get("extras") or {}
        if name in _WATCHED:
            assert extras == {"inbox_stall_s": 15.0}, name
        else:
            assert "inbox_stall_s" not in extras, name
