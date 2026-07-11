"""Contract-тесты: реализации соответствуют Protocol'ам interfaces.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.recipe.interfaces import (
    RecipeEngineProtocol,
    RecipeManagerProtocol,
    StoreProtocol,
)
from multiprocess_framework.modules.recipe.manager import RecipeManager
from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    d = tmp_path / "recipes"
    d.mkdir()
    return d


def test_tree_store_satisfies_store_protocol() -> None:
    # given реальный TreeStore
    store = TreeStore({"cameras": {}})
    # then он соответствует StoreProtocol (has/get/transaction)
    assert isinstance(store, StoreProtocol)


def test_recipe_engine_satisfies_engine_protocol(recipes_dir: Path) -> None:
    engine = RecipeEngine(store=TreeStore(), recipes_dir=recipes_dir)
    assert isinstance(engine, RecipeEngineProtocol)


def test_recipe_manager_satisfies_manager_protocol(recipes_dir: Path) -> None:
    engine = RecipeEngine(store=TreeStore(), recipes_dir=recipes_dir)
    manager = RecipeManager(engine=engine)
    assert isinstance(manager, RecipeManagerProtocol)


def test_v3_blueprint_load_does_not_replay(recipes_dir: Path) -> None:
    # Post (RecipeEngineProtocol.load): v3-blueprint помечается active без replay.
    import yaml

    store = TreeStore({"cameras": {}})
    # migration_fn, который бы испортил файл, если бы v3 не короткозамкнулся
    engine = RecipeEngine(
        store=store,
        recipes_dir=recipes_dir,
        migration_fn=lambda d: {},
        migration_check_fn=lambda d: True,
    )
    path = recipes_dir / "topo.yaml"
    original = {"name": "topo", "version": 3, "blueprint": {"processes": [1, 2]}}
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(original, f, allow_unicode=True)

    deltas = engine.load("topo")

    # v3 → пустые дельты, active установлен, файл НЕ перезаписан миграцией
    assert deltas == []
    assert engine.get_active() == "topo"
    reloaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert reloaded["blueprint"] == {"processes": [1, 2]}
    assert "migrated_from_v1" not in reloaded.get("meta", {})
