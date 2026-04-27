# multiprocess_prototype_v3/frontend/widgets/settings_tab/widget.py
"""
SettingsContainerWidget — drop-in замена SettingsTabWidget.

Левая панель (QListWidget) с секциями + правая (QStackedWidget):
  0: Администрация (placeholder)
  1: Настройки системы (placeholder)
  2: Настройка интерфейса (AppRecipePanel в карточках/таблице)
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QFrame,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from multiprocess_framework.modules.frontend_module.core.schema_config import coerce_schema_config
from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui
from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseTab,
    RegisterBindingContext,
    create_registers_placeholder,
)

from multiprocess_prototype_v3.frontend.managers.access_context import AccessContext
from multiprocess_prototype_v3.frontend.managers.recipe_manager_protocol import (
    RecipeManagerProtocol,
)
from multiprocess_prototype_v3.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from ..settings_recipe_widget import AppRecipePanelWidget as AppRecipePanel
from ..settings_recipe_widget.schemas import RecipesTabConfig
from ..tabs_setting.recipes_settings_tab.schemas import SettingsTabConfig
from ..view_mode_toggle import ViewModeToggle
from .admin_section import AdminSectionWidget
from .settings_nav_panel import SettingsNavigationPanel
from .history_section import HistorySectionWidget
from .prefs_store import KEY_SETTINGS_MODE, get_view_mode, set_view_mode
from .system_section import SystemSettingsSectionWidget
from .ui_section import UiSettingsSectionWidget


class SettingsContainerWidget(BaseTab):
    """Вкладка настроек: навигация по секциям + карточный/табличный вид."""

    def __init__(
        self,
        *,
        registers_manager: IRegistersManagerGui | None = None,
        ui: SettingsTabConfig | dict | None = None,
        recipe_manager: RecipeManagerProtocol | None = None,
        recipe_access: AccessContext | dict | None = None,
        recipes_tab: dict[str, Any] | None = None,
        processing_tab_ui: dict[str, Any] | None = None,
        touch_keyboard: Any | None = None,
        settings_profile_manager: Any | None = None,
        action_bus: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._action_bus = action_bus
        self._config = coerce_schema_config(ui, SettingsTabConfig)
        self._recipe_manager = recipe_manager
        self._access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(
                recipe_access if isinstance(recipe_access, dict) else None
            )
        )
        self._recipes_tab_dict = dict(recipes_tab or {})
        self._processing_tab_ui_dict = dict(processing_tab_ui or {})
        _rtab = coerce_schema_config(self._recipes_tab_dict, RecipesTabConfig)
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(_rtab, "touch_keyboard", None)
        )
        self._settings_profile_manager = settings_profile_manager
        self._init_ui()

    @property
    def registers_manager(self) -> IRegistersManagerGui | None:
        return self._registers_manager

    def _init_ui(self) -> None:
        binding = RegisterBindingContext(rm=self._registers_manager)
        layout = QVBoxLayout(self)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Настройки"))
            layout.addStretch()
            return

        # --- Построить AppRecipePanel (логика из SettingsTabWidget._init_ui) ---
        rtab = coerce_schema_config(self._recipes_tab_dict, RecipesTabConfig)
        app_panel = AppRecipePanel(
            ui=rtab,
            recipes_tab_dict=self._recipes_tab_dict,
            processing_tab_ui_dict=self._processing_tab_ui_dict,
            recipe_manager=self._recipe_manager,
            recipe_access=self._access_ctx,
            touch_keyboard=self._touch_keyboard,
        )

        # --- Восстановить режим из QSettings (user preference, не свойство рецепта) ---
        initial_mode = get_view_mode(KEY_SETTINGS_MODE, default=0)

        # --- Секции ---
        admin = AdminSectionWidget()
        system = SystemSettingsSectionWidget()
        system.set_mode(initial_mode)
        ui_section = UiSettingsSectionWidget(app_panel, initial_mode=initial_mode)
        history = HistorySectionWidget(action_bus=self._action_bus)
        self._ui_section = ui_section
        self._system_section = system
        self._history_section = history

        # --- Layout: слева список, справа содержимое ---
        h_layout = QHBoxLayout()
        layout.addLayout(h_layout)

        # Навигационная панель секций
        self._nav = SettingsNavigationPanel()
        h_layout.addWidget(self._nav)

        # Правая часть: toolbar + stack
        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)

        # Toolbar: ViewModeToggle справа
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        self._view_toggle = ViewModeToggle()
        self._view_toggle.mode_changed.connect(self._on_mode_changed)
        self._view_toggle.set_mode(initial_mode)
        toolbar.addWidget(self._view_toggle)
        right_layout.addLayout(toolbar)

        # Stack
        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(admin)      # 0
        self._content_stack.addWidget(system)      # 1
        self._content_stack.addWidget(ui_section)  # 2
        self._content_stack.addWidget(history)     # 3
        right_layout.addWidget(self._content_stack, 1)
        h_layout.addWidget(right, 1)

        # Связи — DEFAULT_INDEX=2 уже установлен в SettingsNavigationPanel
        self._nav.selection_changed.connect(self._content_stack.setCurrentIndex)

    def _on_mode_changed(self, mode: int) -> None:
        """Переключить режим + persistence (QSettings) для всех секций со set_mode."""
        set_view_mode(KEY_SETTINGS_MODE, mode)
        if hasattr(self, "_ui_section"):
            self._ui_section.set_mode(mode)
        if hasattr(self, "_system_section"):
            self._system_section.set_mode(mode)
