# multiprocess_prototype/frontend/widgets/tabs_setting/settings_tab/widget.py
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

from multiprocess_prototype.managers.access_context import AccessContext

from ..recipes_tab.recipe_slot_table_panel import AppRecipePanel
from ..recipes_tab.schemas import RecipesTabConfig

from .schemas import SettingsTabConfig


class SettingsTabWidget(BaseTab):
    """Вкладка настроек: пресеты UI (app-рецепты), редактирование в таблице."""

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[SettingsTabConfig, dict]] = None,
        recipe_manager: Optional[Any] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        recipes_tab: Optional[Dict[str, Any]] = None,
        processing_tab_ui: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ):
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
        self._app_recipe_panel: Optional[AppRecipePanel] = None
        self._init_ui()

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        return self._registers_manager

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Настройки"))
            layout.addStretch()
            return

        assert binding.rm is not None

        rtab = coerce_schema_config(self._recipes_tab_dict, RecipesTabConfig)
        self._app_recipe_panel = AppRecipePanel(
            ui=rtab,
            recipes_tab_dict=self._recipes_tab_dict,
            processing_tab_ui_dict=self._processing_tab_ui_dict,
            recipe_manager=self._recipe_manager,
            recipe_access=self._access_ctx,
        )
        layout.addWidget(self._app_recipe_panel, 1)
        layout.addStretch()
