"""RecipesPresenter — бизнес-логика таба рецептов."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .recipe_io import (
    RECIPES_DIR,
    RecipeInfo,
    delete_recipe,
    load_recipe,
    save_recipe,
    scan_recipes,
)

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext


class RecipesPresenter:
    """Presenter для RecipesTab.

    Управляет 8 слотами рецептов: Load/Save/Delete.
    """

    def __init__(self, ctx: "AppContext", recipes_dir: Path | None = None) -> None:
        self._ctx = ctx
        self._recipes_dir = recipes_dir or RECIPES_DIR
        self._recipes: dict[int, RecipeInfo] = {}  # slot -> info
        self.refresh()

    def refresh(self) -> dict[int, RecipeInfo]:
        """Перечитать рецепты из файловой системы."""
        infos = scan_recipes(self._recipes_dir)
        self._recipes = {info.slot: info for info in infos}
        return self._recipes

    def get_slot_states(self) -> list[str]:
        """Состояния слотов для SlotSelector: 'occupied' / 'empty'."""
        return [
            "occupied" if i in self._recipes else "empty"
            for i in range(8)
        ]

    def get_slot_labels(self) -> list[str]:
        """Метки слотов для SlotSelector."""
        return [
            self._recipes[i].name if i in self._recipes else f"Слот {i}"
            for i in range(8)
        ]

    def get_recipe_info(self, slot: int) -> RecipeInfo | None:
        """Получить информацию о рецепте в слоте."""
        return self._recipes.get(slot)

    def save_to_slot(self, slot: int, name: str, description: str) -> None:
        """Сохранить текущую конфигурацию как рецепт в слот.

        Snapshot = текущий topology dict из AppContext.config.
        """
        topology = self._ctx.config.get("topology", {})
        path = self._recipes_dir / f"recipe_{slot}.yaml"
        save_recipe(path, name, description, topology)
        self.refresh()

    def load_from_slot(self, slot: int) -> dict[str, Any] | None:
        """Загрузить рецепт из слота. Возвращает dict или None."""
        info = self._recipes.get(slot)
        if info is None:
            return None
        return load_recipe(info.path)

    def delete_from_slot(self, slot: int) -> bool:
        """Удалить рецепт из слота."""
        info = self._recipes.get(slot)
        if info is None:
            return False
        result = delete_recipe(info.path)
        self.refresh()
        return result
