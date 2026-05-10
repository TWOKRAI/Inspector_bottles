"""Тесты TopologyHolder и RecipesPresenter.apply_recipe (Phase 11)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.frontend.topology_holder import TopologyHolder
from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import RecipesPresenter
from multiprocess_prototype.frontend.widgets.tabs.recipes.recipe_io import save_recipe


# ---------------------------------------------------------------------------
# Вспомогательный FakeAppContext
# ---------------------------------------------------------------------------

@dataclass
class FakeAppContext:
    """Минимальный контекст приложения для изоляции тестов."""
    config: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.extras.get(key, default)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def holder() -> TopologyHolder:
    """TopologyHolder с начальной topology."""
    return TopologyHolder(initial={"processes": [], "version": 1})


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Временная директория для рецептов."""
    d = tmp_path / "recipes"
    d.mkdir()
    return d


@pytest.fixture
def ctx_with_holder(holder: TopologyHolder) -> FakeAppContext:
    """FakeAppContext, у которого extras["topology_holder"] = holder."""
    ctx = FakeAppContext(
        config={"topology": {}},
        extras={"topology_holder": holder},
    )
    return ctx


@pytest.fixture
def presenter_with_holder(ctx_with_holder: FakeAppContext, recipes_dir: Path) -> RecipesPresenter:
    """RecipesPresenter, подключённый к TopologyHolder."""
    return RecipesPresenter(ctx_with_holder, recipes_dir=recipes_dir)


# ---------------------------------------------------------------------------
# Тесты TopologyHolder
# ---------------------------------------------------------------------------

class TestTopologyHolder:
    def test_topology_holder_get_set(self, holder: TopologyHolder) -> None:
        """topology property возвращает текущее значение после set_topology."""
        new_topo = {"processes": [{"name": "cam"}], "version": 2}
        holder.set_topology(new_topo)
        assert holder.topology == new_topo

    def test_topology_holder_returns_previous(self, holder: TopologyHolder) -> None:
        """set_topology возвращает deep copy предыдущей topology."""
        initial = {"processes": [], "version": 1}
        new_topo = {"processes": [{"name": "cam"}], "version": 2}
        # holder инициализирован через fixture — сохраняем копию initial
        holder.set_topology(initial)
        prev = holder.set_topology(new_topo)
        # prev должен быть == initial, но не тем же объектом
        assert prev == initial
        assert prev is not holder.topology  # deep copy, не ссылка

    def test_topology_holder_notifies_callbacks(self, holder: TopologyHolder) -> None:
        """callback вызывается при каждом set_topology."""
        received: list[dict] = []
        holder.on_changed(received.append)
        new_topo = {"processes": [], "version": 99}
        holder.set_topology(new_topo)
        assert len(received) == 1
        assert received[0] == new_topo

    def test_topology_holder_callback_receives_new_value(self, holder: TopologyHolder) -> None:
        """callback получает именно новую topology (не старую)."""
        seen_topologies: list[dict] = []
        holder.on_changed(seen_topologies.append)
        holder.set_topology({"a": 1})
        holder.set_topology({"b": 2})
        assert seen_topologies[0] == {"a": 1}
        assert seen_topologies[1] == {"b": 2}

    def test_topology_holder_initial_topology(self) -> None:
        """Начальная topology передаётся через конструктор."""
        initial = {"foo": "bar"}
        h = TopologyHolder(initial=initial)
        assert h.topology == initial


# ---------------------------------------------------------------------------
# Тесты RecipesPresenter.apply_recipe
# ---------------------------------------------------------------------------

class TestRecipesPresenterApply:
    def test_apply_recipe_updates_topology(
        self,
        presenter_with_holder: RecipesPresenter,
        ctx_with_holder: FakeAppContext,
        holder: TopologyHolder,
        recipes_dir: Path,
    ) -> None:
        """apply_recipe заменяет topology в TopologyHolder."""
        recipe_topo = {"processes": [{"name": "proc_1"}], "version": 5}
        save_recipe(recipes_dir / "recipe_0.yaml", "Recipe Alpha", "", recipe_topo)
        presenter_with_holder.refresh()

        presenter_with_holder.apply_recipe(0)

        assert holder.topology == recipe_topo

    def test_apply_empty_slot_returns_none(
        self,
        presenter_with_holder: RecipesPresenter,
    ) -> None:
        """apply_recipe для незаполненного слота возвращает None."""
        result = presenter_with_holder.apply_recipe(7)  # слот пустой
        assert result is None

    def test_save_snapshots_actual_topology(
        self,
        presenter_with_holder: RecipesPresenter,
        holder: TopologyHolder,
        recipes_dir: Path,
    ) -> None:
        """save_to_slot берёт topology из TopologyHolder, а не пустой dict."""
        actual_topo = {"processes": [{"name": "real_process"}], "version": 3}
        holder.set_topology(actual_topo)

        presenter_with_holder.save_to_slot(0, "Snapshot Recipe", "desc")

        from multiprocess_prototype.frontend.widgets.tabs.recipes.recipe_io import load_recipe
        data = load_recipe(recipes_dir / "recipe_0.yaml")
        assert data["topology"] == actual_topo

    def test_apply_returns_previous_for_undo(
        self,
        presenter_with_holder: RecipesPresenter,
        holder: TopologyHolder,
        recipes_dir: Path,
    ) -> None:
        """apply_recipe возвращает dict с ключами previous/current/recipe_name."""
        old_topo = {"processes": [], "version": 1}
        new_topo = {"processes": [{"name": "p"}], "version": 2}
        holder.set_topology(old_topo)

        save_recipe(recipes_dir / "recipe_1.yaml", "My Recipe", "", new_topo)
        presenter_with_holder.refresh()

        result = presenter_with_holder.apply_recipe(1)

        assert result is not None
        assert "previous" in result
        assert "current" in result
        assert "recipe_name" in result
        assert result["previous"] == old_topo
        assert result["current"] == new_topo
        assert result["recipe_name"] == "My Recipe"

    def test_apply_recipe_empty_topology_in_file_returns_none(
        self,
        presenter_with_holder: RecipesPresenter,
        recipes_dir: Path,
    ) -> None:
        """apply_recipe возвращает None если topology в файле пустая."""
        # Сохраняем рецепт с явно пустой topology
        save_recipe(recipes_dir / "recipe_2.yaml", "Empty Topo", "", {})
        presenter_with_holder.refresh()

        result = presenter_with_holder.apply_recipe(2)
        # topology пустая → apply должен вернуть None
        assert result is None
