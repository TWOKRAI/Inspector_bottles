# multiprocess_prototype_v3/frontend/widgets/tabs_setting/recipes_settings_tab/widget.py
"""
SettingsTabWidget — вкладка настроек.

Редактирование параметров UI (схемы app-рецепта) только через таблицу
AppRecipePanel; отдельные слайдеры/чекбоксы к регистрам не используются.

Доступность: RegisterBindingContext + IRegistersManagerGui; при отсутствии rm —
заглушка (см. TAB_STRUCTURE.md).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from frontend_module.widgets.tabs import BaseTab
from frontend_module.widgets.tabs import RegisterBindingContext, create_registers_placeholder
from frontend_module.core.qt_imports import QVBoxLayout, QWidget
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype_v3.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts
from multiprocess_prototype_v3.managers.access_context import AccessContext
from multiprocess_prototype_v3.managers.recipe_manager_protocol import RecipeManagerProtocol

from ...settings_recipe_widget import AppRecipePanelWidget as AppRecipePanel
from ...settings_recipe_widget.schemas import RecipesTabConfig

from .schemas import SettingsTabConfig


class SettingsTabWidget(BaseTab):
    """Вкладка настроек: пресеты UI (app-рецепты), редактирование в таблице."""

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[SettingsTabConfig, dict]] = None,
        recipe_manager: Optional[RecipeManagerProtocol] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        recipes_tab: Optional[Dict[str, Any]] = None,
        processing_tab_ui: Optional[Dict[str, Any]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[QWidget] = None,
    ):
        """AppRecipePanel (таблица UI-схем) или заглушка без rm."""
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._config = coerce_schema_config(ui, SettingsTabConfig)
        self._recipe_manager = recipe_manager
        self._access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._recipes_tab_dict = dict(recipes_tab or {})
        self._processing_tab_ui_dict = dict(processing_tab_ui or {})
        _rtab = coerce_schema_config(self._recipes_tab_dict, RecipesTabConfig)
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(_rtab, "touch_keyboard", None)
        )
        self._app_recipe_panel: Optional[AppRecipePanel] = None
        self._init_ui()

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        """Rm вкладки."""
        return self._registers_manager

    def _init_ui(self) -> None:
        """Placeholder или AppRecipePanel с агрегатом recipes + processing UI."""
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Настройки"))
            layout.addStretch()
            return

        assert binding.rm is not None

        # --- Панель app-рецепта: слот + таблица полей схем интерфейса ---
        rtab = coerce_schema_config(self._recipes_tab_dict, RecipesTabConfig)
        self._app_recipe_panel = AppRecipePanel(
            ui=rtab,
            recipes_tab_dict=self._recipes_tab_dict,
            processing_tab_ui_dict=self._processing_tab_ui_dict,
            recipe_manager=self._recipe_manager,
            recipe_access=self._access_ctx,
            touch_keyboard=self._touch_keyboard,
        )
        layout.addWidget(self._app_recipe_panel, 1)
        layout.addStretch()
