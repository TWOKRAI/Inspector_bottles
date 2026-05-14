"""Тесты для RecipesTab."""

from __future__ import annotations
from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.recipes.recipe_io import (
    delete_recipe,
    load_recipe,
    save_recipe,
    scan_recipes,
)
from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import RecipesPresenter
from multiprocess_prototype.frontend.widgets.tabs.recipes.tab import RecipesTab


class TestRecipeIO:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "recipe_0.yaml"
        save_recipe(path, "Test Recipe", "A test", {"name": "test_topo"})
        assert path.exists()

        data = load_recipe(path)
        assert data["name"] == "Test Recipe"
        assert data["description"] == "A test"
        assert "topology" in data
        assert data["topology"]["name"] == "test_topo"

    def test_scan_recipes(self, tmp_path):
        save_recipe(tmp_path / "recipe_0.yaml", "R0", "", {})
        save_recipe(tmp_path / "recipe_3.yaml", "R3", "", {})

        infos = scan_recipes(tmp_path)
        assert len(infos) == 2
        slots = {info.slot for info in infos}
        assert slots == {0, 3}

    def test_scan_empty_dir(self, tmp_path):
        infos = scan_recipes(tmp_path)
        assert infos == []

    def test_delete_recipe(self, tmp_path):
        path = tmp_path / "recipe_0.yaml"
        save_recipe(path, "R", "", {})
        assert path.exists()

        result = delete_recipe(path)
        assert result is True
        assert not path.exists()

    def test_delete_nonexistent(self, tmp_path):
        path = tmp_path / "nonexistent.yaml"
        result = delete_recipe(path)
        assert result is True  # missing_ok=True


class TestRecipesPresenter:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.config = {"topology": {"name": "test_topology", "processes": []}}
        ctx.extras = {"topology": {"name": "test_topology", "processes": []}}
        ctx.get = lambda key, default=None: ctx.extras.get(key, default)
        return ctx

    def test_refresh_empty(self, tmp_path):
        ctx = self._make_ctx()
        p = RecipesPresenter(ctx, recipes_dir=tmp_path)
        assert len(p._recipes) == 0

    def test_save_and_refresh(self, tmp_path):
        ctx = self._make_ctx()
        p = RecipesPresenter(ctx, recipes_dir=tmp_path)
        p.save_to_slot(0, "My Recipe", "Test desc")
        assert 0 in p._recipes
        assert p._recipes[0].name == "My Recipe"

    def test_get_slot_states(self, tmp_path):
        ctx = self._make_ctx()
        p = RecipesPresenter(ctx, recipes_dir=tmp_path)
        p.save_to_slot(2, "R2", "")
        states = p.get_slot_states()
        assert states[2] == "occupied"
        assert states[0] == "empty"

    def test_get_slot_labels(self, tmp_path):
        ctx = self._make_ctx()
        p = RecipesPresenter(ctx, recipes_dir=tmp_path)
        p.save_to_slot(1, "Camera Setup", "")
        labels = p.get_slot_labels()
        assert labels[1] == "Camera Setup"
        assert labels[0] == "Слот 0"

    def test_delete_from_slot(self, tmp_path):
        ctx = self._make_ctx()
        p = RecipesPresenter(ctx, recipes_dir=tmp_path)
        p.save_to_slot(0, "R", "")
        assert 0 in p._recipes
        p.delete_from_slot(0)
        assert 0 not in p._recipes

    def test_load_from_slot(self, tmp_path):
        ctx = self._make_ctx()
        p = RecipesPresenter(ctx, recipes_dir=tmp_path)
        p.save_to_slot(0, "R", "desc")
        data = p.load_from_slot(0)
        assert data is not None
        assert data["name"] == "R"

    def test_load_empty_slot(self, tmp_path):
        ctx = self._make_ctx()
        p = RecipesPresenter(ctx, recipes_dir=tmp_path)
        data = p.load_from_slot(5)
        assert data is None


class TestRecipesTab:
    def _make_ctx(self, tmp_path):
        ctx = MagicMock()
        ctx.config = {"topology": {"name": "test", "processes": []}}
        ctx.extras = {"topology": {"name": "test", "processes": []}}
        ctx.get = lambda key, default=None: ctx.extras.get(key, default)
        ctx.bindings.return_value = None
        ctx.action_bus.return_value = None
        # Патчим RECIPES_DIR через presenter
        return ctx

    def test_create(self, qtbot, tmp_path):
        ctx = self._make_ctx(tmp_path)
        tab = RecipesTab(ctx)
        # Подменим recipes_dir в presenter
        tab._presenter._recipes_dir = tmp_path
        tab._presenter.refresh()
        tab._sync_slots()
        qtbot.addWidget(tab)
        assert tab is not None

    def test_slot_selection_empty(self, qtbot, tmp_path):
        ctx = self._make_ctx(tmp_path)
        tab = RecipesTab(ctx)
        tab._presenter._recipes_dir = tmp_path
        tab._presenter.refresh()
        qtbot.addWidget(tab)
        tab._on_slot_selected(0)
        assert tab._name_edit.text() == ""

    def test_save_and_select(self, qtbot, tmp_path):
        ctx = self._make_ctx(tmp_path)
        tab = RecipesTab(ctx)
        tab._presenter._recipes_dir = tmp_path
        tab._presenter.refresh()
        qtbot.addWidget(tab)

        tab._selected_slot = 0
        tab._name_edit.setText("Test Recipe")
        tab._on_action("save")

        tab._on_slot_selected(0)
        assert tab._name_edit.text() == "Test Recipe"
