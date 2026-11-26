"""Task 2.2d, REDS 10: блок ``presence_watch`` в рецептах букв (YAML читается как данные).

Порог ``min_confidence`` обязан совпадать с порогом ``word_layout``: иначе индикатор называет
диск нормальным, а раскладка его молча отбрасывает (или наоборот). Живую правку одного
регистра этот тест не видит.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from Plugins.processing.presence_watch.registers import PresenceWatchRegisters

# tests/ -> presence_watch -> processing -> Plugins -> корень репозитория
_RECIPES = Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "recipes"


def _plugins(recipe: dict, process_name: str) -> list[dict]:
    processes = recipe["blueprint"]["processes"]
    found = [p for p in processes if p["process_name"] == process_name]
    assert len(found) == 1, (process_name, len(found))
    return found[0]["plugins"]


@pytest.mark.parametrize("name", ["hikvision_letter_robot", "letter_robot_sim"])
def test_letter_recipes_pin_presence_watch(name: str) -> None:
    recipe = yaml.safe_load((_RECIPES / f"{name}.yaml").read_text(encoding="utf-8"))
    node = _plugins(recipe, "recog")[-1]

    assert node["plugin_name"] == "presence_watch"
    assert node["plugin_class"] == "Plugins.processing.presence_watch.plugin.PresenceWatchPlugin"
    assert node["config"] == {
        "absent_after_s": 10.0,
        "text_absent": "нет диска",
        "text_weak": "слабое распознавание",
        "min_confidence": 0.5,
    }
    assert set(node["config"]) <= set(PresenceWatchRegisters.model_fields)
    # readiness: {severity: {out_of_spec: check_function}} сделал бы «нет диска» аварией
    assert "readiness" not in node
    assert "readiness" not in node["config"]

    word_layout = [p for p in _plugins(recipe, "layout") if p["plugin_name"] == "word_layout"]
    assert len(word_layout) == 1
    assert node["config"]["min_confidence"] == word_layout[0]["config"]["min_confidence"]
