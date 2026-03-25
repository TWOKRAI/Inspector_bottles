# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/widget.py
"""
RecipesTabWidget — вкладка рецептов: только рецепты регистров (параметры алгоритма).
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from frontend_module.widgets.tabs import BaseTab
from frontend_module.widgets.tabs import RegisterBindingContext, create_registers_placeholder
from frontend_module.core.qt_imports import QScrollArea, QVBoxLayout, QWidget, pyqtSignal
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts
from multiprocess_prototype.managers.access_context import AccessContext
from multiprocess_prototype.managers.recipe_manager_protocol import RecipeManagerProtocol

from ...settings_recipe_widget.schemas import RecipesTabConfig
from ...recipes_widget import RegisterRecipePanelWidget as RegisterRecipePanel


class RecipesTabWidget(BaseTab):
    """Вкладка «Рецепты»: слот и таблица полей регистров."""

    recipe_load_requested = pyqtSignal(int)
    recipe_save_requested = pyqtSignal(int)
    recipe_default_requested = pyqtSignal()

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[RecipesTabConfig, dict]] = None,
        recipe_manager: Optional[RecipeManagerProtocol] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        on_recipe_applied: Optional[Callable[[int], None]] = None,
        on_recipe_saved: Optional[Callable[[int], None]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[QWidget] = None,
    ):
        """Панель рецептов регистров в QScrollArea или заглушка без rm."""
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._ui = coerce_schema_config(ui, RecipesTabConfig)
        self._recipe_manager = recipe_manager
        self._access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._on_recipe_applied = on_recipe_applied
        self._on_recipe_saved = on_recipe_saved
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(self._ui, "touch_keyboard", None)
        )
        self._register_panel: Optional[RegisterRecipePanel] = None
        self._init_ui()

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        """Rm для внешних обновлений."""
        return self._registers_manager

    def _init_ui(self) -> None:
        """Placeholder или RegisterRecipePanel внутри прокручиваемой области."""
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        # --- Нет регистров: только заглушка ---
        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Рецепты"))
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None

        # --- Панель рецептов + прокрутка + сигналы load/save/default ---
        self._register_panel = RegisterRecipePanel(
            rm=rm,
            ui=self._ui,
            recipe_manager=self._recipe_manager,
            recipe_access=self._access_ctx,
            touch_keyboard=self._touch_keyboard,
            on_recipe_applied=self._on_recipe_applied,
            on_recipe_saved=self._on_recipe_saved,
        )
        self._register_panel.load_requested.connect(self.recipe_load_requested.emit)
        self._register_panel.save_requested.connect(self.recipe_save_requested.emit)
        self._register_panel.default_requested.connect(self.recipe_default_requested.emit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        v = QVBoxLayout(inner)
        v.addWidget(self._register_panel, 1)
        layout.addWidget(scroll, 1)

    def refresh_from_registers(self) -> None:
        """Обновить таблицу регистров (например после внешней загрузки рецепта)."""
        if self._register_panel is not None:
            self._register_panel.refresh_from_registers()
