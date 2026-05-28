# -*- coding: utf-8 -*-
"""Тесты RecipesTab (Qt MVP, Task 5.7; Task E.2 / F.4: AppServices DI + RecipeStore Protocol).

Qt-тесты через pytest-qt (qtbot fixture).
Task F.4: presenter работает через FakeRecipeStore напрямую (без _rm bridge).

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.7
      plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md Task F.4
"""

from __future__ import annotations

import pytest

from PySide6.QtWidgets import QMessageBox

from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
from multiprocess_prototype.frontend.widgets.tabs.recipes.tab import RecipesTab
from multiprocess_prototype.frontend.widgets.tabs.recipes.view import IRecipesView

from ._helpers import make_recipes_services


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_recipe_raw(slug: str = "cup") -> dict:
    """Минимальный v2-рецепт raw dict."""
    return {
        "version": 2,
        "name": slug,
        "description": "Тестовый рецепт",
        "blueprint": {
            "processes": [{"process_name": "worker", "plugins": ["p1", "p2"]}],
            "wires": [],
        },
        "active_services": ["webcam"],
        "display_bindings": [{"node_id": "s", "display_id": "d"}],
    }


def _make_tab(
    qtbot,
    slugs: list[str] | None = None,
) -> RecipesTab:
    """Создать RecipesTab с AppServices (FakeRecipeStore с raw-данными)."""
    raw: dict[str, dict] = {}
    if slugs:
        for slug in slugs:
            raw[slug] = _make_recipe_raw(slug)
    store = FakeRecipeStore(raw=raw)
    services = make_recipes_services(recipes=store)
    tab = RecipesTab(services)
    qtbot.addWidget(tab)
    return tab


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestRecipesTabQt:
    """Qt-тесты RecipesTab через pytest-qt."""

    def test_recipes_tab_creates_without_error(self, qtbot: pytest.FixtureRequest) -> None:
        """RecipesTab создаётся без исключений с mock ctx."""
        tab = _make_tab(qtbot)
        assert tab is not None
        assert hasattr(tab, "_presenter")
        assert hasattr(tab, "_form_widget")

    def test_isinstance_irecipes_view(self, qtbot: pytest.FixtureRequest) -> None:
        """isinstance(tab, IRecipesView) == True (runtime_checkable Protocol)."""
        tab = _make_tab(qtbot)
        assert isinstance(tab, IRecipesView)

    def test_refresh_list_adds_items(self, qtbot: pytest.FixtureRequest) -> None:
        """refresh_list(['a', 'b']) -> nav содержит 2 элемента."""
        tab = _make_tab(qtbot)
        # Перестраиваем nav с конкретными slug'ами
        tab.refresh_list(["recipe_a", "recipe_b"])
        assert tab.nav_widget.count() == 2

    def test_show_recipe_populates_form(self, qtbot: pytest.FixtureRequest) -> None:
        """show_recipe с mock данными -> форма заполнена."""
        tab = _make_tab(qtbot)
        data = {
            "name": "Тестовый рецепт",
            "description": "Описание теста",
            "version": 2,
            "created": "2026-05-01",
            "modified": "2026-05-26",
            "blueprint": {
                "processes": [{"process_name": "worker", "plugins": ["p1", "p2"]}],
                "wires": [],
            },
            "active_services": ["webcam"],
            "display_bindings": [{"node_id": "s", "display_id": "d"}],
        }
        tab.show_recipe("test_recipe", data)

        assert tab._form_widget.name_edit.text() == "Тестовый рецепт"
        assert "2026-05-01" in tab._form_widget.created_label.text()
        # Сводка blueprint содержит количество процессов
        summary = tab._form_widget.summary_label.text()
        assert "Процессы: 1" in summary
        assert "Плагины: 2" in summary
        assert "Сервисы: 1" in summary
        assert "Дисплеи: 1" in summary

    def test_set_buttons_state_no_selection(self, qtbot: pytest.FixtureRequest) -> None:
        """set_buttons_state(has_selection=False, is_active=False) -> кнопки disabled."""
        tab = _make_tab(qtbot)
        tab.set_buttons_state(has_selection=False, is_active=False)

        assert not tab._duplicate_btn.isEnabled()
        assert not tab._delete_btn.isEnabled()
        assert not tab._activate_btn.isEnabled()
        # «Создать» всегда активна
        assert tab._create_btn.isEnabled()
        # «Открыть в Pipeline» постоянно disabled (Task 7a)
        assert not tab._pipeline_btn.isEnabled()

    def test_set_buttons_state_with_selection(self, qtbot: pytest.FixtureRequest) -> None:
        """set_buttons_state(has_selection=True, is_active=False) -> кнопки enabled."""
        tab = _make_tab(qtbot)
        tab.set_buttons_state(has_selection=True, is_active=False)

        assert tab._duplicate_btn.isEnabled()
        assert tab._delete_btn.isEnabled()
        # is_active=False -> «Сделать активным» enabled
        assert tab._activate_btn.isEnabled()

    def test_set_buttons_state_already_active(self, qtbot: pytest.FixtureRequest) -> None:
        """set_buttons_state(has_selection=True, is_active=True) -> activate disabled."""
        tab = _make_tab(qtbot)
        tab.set_buttons_state(has_selection=True, is_active=True)

        # Дублировать/Удалить активны, но «Сделать активным» — нет (уже активен)
        assert tab._duplicate_btn.isEnabled()
        assert tab._delete_btn.isEnabled()
        assert not tab._activate_btn.isEnabled()

    def test_confirm_delete_returns_bool(self, qtbot: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
        """confirm_delete возвращает True при Yes, False при No."""
        tab = _make_tab(qtbot)

        # Monkeypatch: симулировать ответ Yes
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        result = tab.confirm_delete("test_recipe")
        assert result is True

        # Monkeypatch: симулировать ответ No
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.No,
        )
        result = tab.confirm_delete("test_recipe")
        assert result is False

    def test_show_recipe_none_clears_form(self, qtbot: pytest.FixtureRequest) -> None:
        """show_recipe(None, None) -> форма очищается без ошибок."""
        tab = _make_tab(qtbot)
        # Сначала заполняем
        tab.show_recipe("r", {"name": "R", "description": "D", "version": 2})
        # Затем очищаем
        tab.show_recipe(None, None)
        assert tab._form_widget.name_edit.text() == ""
        assert tab._form_widget.version_label.text() == "—"

    def test_refresh_list_empty_clears_nav(self, qtbot: pytest.FixtureRequest) -> None:
        """refresh_list([]) -> nav пустой, кнопки (кроме Создать) disabled."""
        tab = _make_tab(qtbot, slugs=["old_recipe"])
        tab.refresh_list([])
        assert tab.nav_widget.count() == 0

    def test_pipeline_button_always_disabled(self, qtbot: pytest.FixtureRequest) -> None:
        """«Открыть в Pipeline» постоянно disabled (Task 7a)."""
        tab = _make_tab(qtbot)
        # Даже после set_buttons_state True — Pipeline остаётся disabled
        tab.set_buttons_state(has_selection=True, is_active=False)
        assert not tab._pipeline_btn.isEnabled()
