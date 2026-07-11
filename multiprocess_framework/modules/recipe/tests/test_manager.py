"""Contract-тесты RecipeManager — CRUD + state-sync + duplicate (инъекция writer)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from multiprocess_framework.modules.recipe.manager import RecipeManager
from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture
def engine(recipes_dir: Path) -> RecipeEngine:
    return RecipeEngine(store=TreeStore({"cameras": {}}), recipes_dir=recipes_dir)


def _write_v2(recipes_dir: Path, name: str) -> None:
    recipe = {"meta": {"name": name, "version": 2}, "data": {}}
    with open(recipes_dir / f"{name}.yaml", "w", encoding="utf-8") as f:
        yaml.dump(recipe, f, allow_unicode=True)


def _write_v3(recipes_dir: Path, name: str) -> None:
    recipe = {"name": name, "version": 3, "blueprint": {"processes": []}}
    with open(recipes_dir / f"{name}.yaml", "w", encoding="utf-8") as f:
        yaml.dump(recipe, f, allow_unicode=True)


# ------------------------------------------------------------------
# CRUD-делегация + state-sync
# ------------------------------------------------------------------


def test_list_delegates_to_engine(engine: RecipeEngine, recipes_dir: Path) -> None:
    _write_v2(recipes_dir, "alpha")
    _write_v2(recipes_dir, "beta")
    manager = RecipeManager(engine=engine)
    assert manager.list() == ["alpha", "beta"]


def test_load_updates_state_proxy(engine: RecipeEngine, recipes_dir: Path) -> None:
    _write_v2(recipes_dir, "cup")
    proxy = MagicMock()
    manager = RecipeManager(engine=engine, state_proxy=proxy)
    manager.load("cup")
    proxy.set.assert_called_with("recipes.active", "cup")


def test_delete_active_resets_state(engine: RecipeEngine, recipes_dir: Path) -> None:
    _write_v2(recipes_dir, "cup")
    proxy = MagicMock()
    manager = RecipeManager(engine=engine, state_proxy=proxy)
    manager.load("cup")
    manager.delete("cup")
    # последний вызов set — сброс active в None
    proxy.set.assert_called_with("recipes.active", None)


def test_read_recipe_returns_dict_or_none(engine: RecipeEngine, recipes_dir: Path) -> None:
    _write_v3(recipes_dir, "cup")
    manager = RecipeManager(engine=engine)
    data = manager.read_recipe("cup")
    assert isinstance(data, dict) and data["name"] == "cup"
    assert manager.read_recipe("missing") is None


# ------------------------------------------------------------------
# duplicate — Pre/Post контракта (ADR-RCP-005: дефолтный comment-preserving writer)
# ------------------------------------------------------------------


def test_duplicate_creates_copy_with_new_name_fallback(engine: RecipeEngine, recipes_dir: Path) -> None:
    # given v3-рецепт, менеджер БЕЗ инъекции (дефолтный comment-preserving writer, ruamel)
    _write_v3(recipes_dir, "src")
    manager = RecipeManager(engine=engine)

    # when дублируем
    assert manager.duplicate("src", "dst") is True

    # then копия существует и имя обновлено
    dst = yaml.safe_load((recipes_dir / "dst.yaml").read_text(encoding="utf-8"))
    assert dst["name"] == "dst"
    assert dst["blueprint"] == {"processes": []}


def test_duplicate_uses_injected_yaml_updater(engine: RecipeEngine, recipes_dir: Path) -> None:
    # given инжектированный writer
    _write_v3(recipes_dir, "src")
    updater = MagicMock()
    manager = RecipeManager(engine=engine, yaml_updater=updater)

    # when дублируем
    assert manager.duplicate("src", "dst") is True

    # then writer вызван с top-level name (v3-формат)
    updater.assert_called_once()
    args = updater.call_args.args
    assert args[1] == {"name": "dst"}


def test_duplicate_meta_name_for_legacy(engine: RecipeEngine, recipes_dir: Path) -> None:
    # given legacy config-snapshot (meta.name), инжектированный writer
    _write_v2(recipes_dir, "src")
    updater = MagicMock()
    manager = RecipeManager(engine=engine, yaml_updater=updater)

    assert manager.duplicate("src", "dst") is True
    # legacy: имя пишется в meta.name
    args = updater.call_args.args
    assert args[1]["meta"]["name"] == "dst"


def test_duplicate_rejects_empty_slug(engine: RecipeEngine) -> None:
    # Pre-нарушение: пустой slug → False без исключения
    manager = RecipeManager(engine=engine)
    assert manager.duplicate("", "dst") is False
    assert manager.duplicate("src", "") is False


def test_duplicate_rejects_missing_source(engine: RecipeEngine) -> None:
    manager = RecipeManager(engine=engine)
    assert manager.duplicate("nope", "dst") is False


def test_duplicate_rejects_existing_target(engine: RecipeEngine, recipes_dir: Path) -> None:
    _write_v3(recipes_dir, "src")
    _write_v3(recipes_dir, "dst")
    manager = RecipeManager(engine=engine)
    assert manager.duplicate("src", "dst") is False
