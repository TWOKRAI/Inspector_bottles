# multiprocess_prototype/frontend/widgets/settings_recipe_widget/panel_widget.py
"""Панель app-рецептов (UI-схемы): AppRecipePanelWidget на базе RecipePanelBase."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from multiprocess_prototype.frontend.managers.access_context import AccessContext
from multiprocess_prototype.frontend.managers.app_recipe_aggregate import build_default_app_aggregate
from multiprocess_prototype.frontend.managers.recipe_manager_protocol import RecipeManagerProtocol

from .schemas import RecipesTabConfig
from ...base.recipe_panel_base import RecipePanelBase
from .model import AppRecipeModel
from .presenter import AppRecipePresenter


class AppRecipePanelWidget(RecipePanelBase[AppRecipeModel]):
    """Слот и таблица полей app-рецепта (без регистровых слайдеров)."""

    def __init__(
        self,
        *,
        ui: Optional[Union[RecipesTabConfig, dict]] = None,
        recipes_tab_dict: Optional[Dict[str, Any]] = None,
        processing_tab_ui_dict: Optional[Dict[str, Any]] = None,
        recipe_manager: Optional[RecipeManagerProtocol] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[Any] = None,
    ) -> None:
        self._touch_keyboard = touch_keyboard
        self._recipes_tab_dict = dict(recipes_tab_dict or {})
        self._processing_tab_ui_dict = dict(processing_tab_ui_dict or {})
        self._extra_recipe_manager = recipe_manager
        self._extra_access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._initial_aggregate = build_default_app_aggregate(
            recipes_tab_dict=self._recipes_tab_dict,
            processing_tab_ui_dict=self._processing_tab_ui_dict,
        )
        super().__init__(registers_manager=None, ui=ui, parent=parent)

    # --- RecipePanelBase абстрактные методы ---

    def _get_box_title(self) -> str:
        return self._ui.group_app_box

    def _get_table_title(self) -> str:
        return self._ui.table_app_group_title

    def _build_tree_data(self) -> list:
        return self._presenter.build_tree_groups()

    # --- BaseWidget lifecycle ---

    def _create_model(self) -> AppRecipeModel:
        agg_copy = dict(self._initial_aggregate)
        return AppRecipeModel(
            ui=self._ui,
            recipes_tab_dict=self._recipes_tab_dict,
            processing_tab_ui_dict=self._processing_tab_ui_dict,
            recipe_manager=self._extra_recipe_manager,
            access_ctx=self._extra_access_ctx,
            app_aggregate=agg_copy,
        )

    def _create_presenter(self, model: Optional[AppRecipeModel]) -> AppRecipePresenter:
        assert model is not None
        return AppRecipePresenter(view=self, model=model)

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        self.refresh_table_rows()
