# -*- coding: utf-8 -*-
"""Hazard-тест автора к Task 6.1: источник ``pult`` не должен гейтиться run-state.

Слепой tester (test_recipe_1_0.py) это свойство не пинит: инъекция «убрать run_gated: false»
краснила только golden-снапшот β, а в sim-рецепте не краснела ничем (матрица инъекций 6.1, И3).

Почему важно: при ``run_gate: true`` (run-state) источник без ``run_gated: false`` гейтится
run-state (пауза источника при STOP), и его ``local``-эмиты встают. Поле «Слово» (``source: param``)
идёт мимо ``produce()`` — через SetPluginConfig → register_update — и гейтом не ломается; свойство
нужно для будущих ``local``-контролов пульта и закреплено планом Phase 6 (Task 6.1, DESIGN).
Ожидаемое значение — литерал ``False``, не вычисляется из кода под тестом.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[7]
_RECIPES_DIR = _PROJECT_ROOT / "multiprocess_prototype" / "recipes"
_RECIPE_NAMES = ["letter_robot_sim", "hikvision_letter_robot"]


def _pult_plugin_config(recipe: str) -> dict[str, Any]:
    from multiprocess_prototype.backend.launch import load_topology_dict
    from multiprocess_prototype.domain.entities.topology import Topology

    topology = Topology.from_dict(load_topology_dict(_RECIPES_DIR / f"{recipe}.yaml")).to_dict()
    procs = [p for p in topology["processes"] if p.get("process_name") == "pult"]
    assert len(procs) == 1, f"процесса pult нет (или он не один): найдено {len(procs)}"
    plugins = [pl for pl in procs[0]["plugins"] if str(pl.get("plugin_class", "")).endswith("ControlPanelPlugin")]
    assert len(plugins) == 1, f"в процессе pult нет ровно одного ControlPanelPlugin: {len(plugins)}"
    return dict(plugins[0]["config"])


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_pult_is_not_run_gated(recipe: str) -> None:
    """В конфиге плагина pult явно ``run_gated: false`` — иначе источник гейтится run-state."""
    config = _pult_plugin_config(recipe)
    assert config.get("run_gated") is False, (
        f"run_gated в {recipe}: {config.get('run_gated')!r}, ожидалось явное False (ключи config: {sorted(config)})"
    )
