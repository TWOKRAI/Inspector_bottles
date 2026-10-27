# -*- coding: utf-8 -*-
"""
Task 1.7 (C-30, design.md §4.2): ``Topology.name/description`` — типизированные поля, не ``metadata``.

Свойства:
  - name/description читаются и пишутся полями модели (не уезжают в ``metadata``);
  - ``None`` в вложенном ``Topology`` не попадает в ``Recipe.to_dict()`` (файл не получает ``name: null``);
  - запись рецепта с новым именем блюпринта кладёт его на верх ``Topology``;
  - порядок ключей ``metadata`` не зависит от ``PYTHONHASHSEED``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from multiprocess_prototype.domain.entities import Recipe, RecipeMeta, Topology
from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore

_MISSING = object()
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _meta() -> RecipeMeta:
    return RecipeMeta(name="demo", created_at="2026-01-01T00:00:00")


def test_topology_name_description_typed_roundtrip() -> None:
    topo = Topology.from_dict({"processes": [], "name": "x", "description": "y"})

    assert getattr(topo, "name", _MISSING) == "x"
    assert getattr(topo, "description", _MISSING) == "y"
    assert topo.metadata == {}

    dumped = topo.to_dict()
    assert dumped["name"] == "x"
    assert dumped["description"] == "y"
    assert Topology.from_dict(dumped) == topo


def test_recipe_to_dict_nested_blueprint_has_no_none_name_description() -> None:
    recipe = Recipe(meta=_meta(), blueprint=Topology())

    blueprint = recipe.to_dict()["blueprint"]

    assert "name" not in blueprint
    assert "description" not in blueprint
    # Прямой дамп вложенной модели (мимо Topology.to_dict) тоже без ключей.
    assert "name" not in Topology().model_dump(mode="json")
    assert "description" not in Topology().model_dump(mode="json")


def test_write_blueprint_name_change_lands_at_top() -> None:
    store = FakeRecipeStore()
    store.write("demo", Recipe(meta=_meta(), blueprint=Topology.from_dict({"name": "old"})))

    store.write("demo", Recipe(meta=_meta(), blueprint=Topology.from_dict({"name": "new"})))

    back = store.read("demo")
    assert back is not None
    assert getattr(back.blueprint, "name", _MISSING) == "new"
    assert "name" not in back.blueprint.metadata
    assert back.to_dict()["blueprint"]["name"] == "new"


_HASH_SEED_SCRIPT = """
import json
from multiprocess_prototype.domain.entities import Topology

topo = Topology.from_dict(
    {
        "processes": [],
        "name": "x",
        "description": "y",
        "display_definitions": [],
        "metadata": {"gui_positions": {}},
    }
)
print(json.dumps(list(topo.metadata)))
"""


def test_metadata_order_independent_of_hash_seed() -> None:
    orders: dict[str, list[str]] = {}
    for seed in ("0", "1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONUTF8": "1"}
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_REPO_ROOT), env.get("PYTHONPATH", "")]))
        proc = subprocess.run(
            [sys.executable, "-c", _HASH_SEED_SCRIPT],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_REPO_ROOT),
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        orders[seed] = json.loads(proc.stdout)

    assert orders == {seed: ["gui_positions", "display_definitions"] for seed in ("0", "1", "2", "3")}
