# -*- coding: utf-8 -*-
"""Общие помощники тестов рецептов 1.0 (`test_recipe_1_0*.py`): путь к рецептам и чтение контролов процесса `pult`.

Не набор тестов (имя не `test_*`, не собирается).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[7]
_RECIPES_DIR = _PROJECT_ROOT / "multiprocess_prototype" / "recipes"
_RECIPE_NAMES = ["letter_robot_sim", "hikvision_letter_robot"]

# Ожидаемый единственный контрол — литералом (критерий А3).
_EXPECTED_WORD_CONTROL = {
    "id": "word",
    "type": "text",
    "source": "param",
    "label": "Слово",
    "target_process": "layout",
    "target_plugin_index": 0,
    "target_field": "target_word",
}

_CONTROL_PANEL_CLASS = "ControlPanelPlugin"


def _recipe_path(name: str) -> Path:
    return _RECIPES_DIR / f"{name}.yaml"


def _topology_dict(name: str) -> dict[str, Any]:
    """Плоская топология рецепта — так её читает загрузчик (``load_topology_dict``)."""
    from multiprocess_prototype.backend.launch import load_topology_dict

    return load_topology_dict(_recipe_path(name))


def _domain_topology_dict(name: str) -> dict[str, Any]:
    """Топология в виде, в котором её держит GUI (domain ``Topology``; конфиг плагина = ``config``)."""
    from multiprocess_prototype.domain.entities.topology import Topology

    return Topology.from_dict(_topology_dict(name)).to_dict()


def _pult_process(topology: dict[str, Any]) -> dict[str, Any]:
    procs = [p for p in topology["processes"] if p.get("process_name") == "pult"]
    assert len(procs) == 1, f"процесса pult нет (или он не один): найдено {len(procs)}"
    return procs[0]


def _pult_controls_raw(name: str) -> list[dict[str, Any]]:
    """Сырой список контролов из конфига ControlPanelPlugin процесса pult (в виде домена GUI)."""
    proc = _pult_process(_domain_topology_dict(name))
    plugins = [pl for pl in proc["plugins"] if str(pl.get("plugin_class", "")).endswith(_CONTROL_PANEL_CLASS)]
    assert len(plugins) == 1, f"в процессе pult нет ровно одного {_CONTROL_PANEL_CLASS}: {len(plugins)}"
    return list(plugins[0]["config"].get("controls") or [])
