# multiprocess_prototype_v3/frontend/widgets/recipes_widget/panel_widget.py
"""Панель рецептов регистров: RegisterRecipePanelWidget на базе RecipePanelBase."""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype_v3.frontend.managers.access_context import AccessContext
from multiprocess_prototype_v3.frontend.managers.recipe_manager_protocol import RecipeManagerProtocol

from ..settings_recipe_widget.schemas import RecipesTabConfig
from .._recipe_panel_base import RecipePanelBase
from .model import RegisterRecipeModel
from .presenter import RegisterRecipePresenter
from .recipe_rows import group_rows_by_register


class RegisterRecipePanelWidget(RecipePanelBase[RegisterRecipeModel]):
    """Слот, загрузка/сохранение рецепта регистров, таблица полей."""

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        rm: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[RecipesTabConfig, dict]] = None,
        recipe_manager: Optional[RecipeManagerProtocol] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        on_recipe_applied: Optional[Callable[[int], None]] = None,
        on_recipe_saved: Optional[Callable[[int], None]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[Any] = None,
    ) -> None:
        resolved = rm if rm is not None else registers_manager
        if resolved is None:
            raise TypeError("RegisterRecipePanelWidget requires rm or registers_manager")
        self._touch_keyboard = touch_keyboard
        self._extra_recipe_manager = recipe_manager
        self._extra_access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._on_recipe_applied_cb = on_recipe_applied
        self._on_recipe_saved_cb = on_recipe_saved
        super().__init__(registers_manager=resolved, ui=ui, parent=parent)

    # --- RecipePanelBase абстрактные методы ---

    def _get_box_title(self) -> str:
        return self._ui.group_register_box

    def _get_table_title(self) -> str:
        return self._ui.table_group_title

    def _build_tree_data(self) -> list:
        rows = self._presenter.build_rows()
        return group_rows_by_register(rows)

    # --- BaseWidget lifecycle ---

    def _create_model(self) -> RegisterRecipeModel:
        assert self._registers_manager is not None
        return RegisterRecipeModel(
            rm=self._registers_manager,
            recipe_manager=self._extra_recipe_manager,
            access_ctx=self._extra_access_ctx,
            ui=self._ui,
            on_recipe_applied=self._on_recipe_applied_cb,
            on_recipe_saved=self._on_recipe_saved_cb,
        )

    def _create_presenter(self, model: Optional[RegisterRecipeModel]) -> RegisterRecipePresenter:
        assert model is not None
        return RegisterRecipePresenter(view=self, model=model)

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        self._presenter.refresh_from_registers()

    # --- Публичный API ---

    def refresh_from_registers(self) -> None:
        """Обновить таблицу после внешней правки регистров."""
        self._presenter.refresh_from_registers()
