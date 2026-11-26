# -*- coding: utf-8 -*-
"""Пин рецептов букв (2.10): камера не паузится, обработанные display показываются только в ``running``.

Ожидаемые значения — литералы (решение владельца 2026-11-26).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.domain.entities.display import DisplayDefinition

_RECIPES = Path(__file__).resolve().parents[1]
_NAMES = ["letter_robot_sim", "hikvision_letter_robot"]


def _load(name: str) -> dict:
    return yaml.safe_load((_RECIPES / f"{name}.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", _NAMES)
def test_camera_is_not_run_gated(name: str) -> None:
    processes = {p["process_name"]: p for p in _load(name)["blueprint"]["processes"]}

    assert processes["camera_0"]["plugins"][0]["config"]["run_gated"] is False


@pytest.mark.parametrize("name", _NAMES)
def test_processed_displays_show_only_in_running(name: str) -> None:
    run_view = {d["id"]: DisplayDefinition.from_dict(d).run_view for d in _load(name)["displays"]}

    assert run_view == {"main": "always", "recog": "running", "mask": "running", "phone": "running"}
