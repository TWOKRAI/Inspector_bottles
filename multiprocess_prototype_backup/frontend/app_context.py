# multiprocess_prototype/frontend/app_context.py
"""
Явный контекст зависимостей вкладок и окон прототипа.

Один объект вместо длинного списка аргументов у create_tab_widget_factory; слои (launcher,
FrontendManager, MVP) не сливаются — меняется только способ передачи ссылок.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from multiprocess_framework.modules.frontend_module.core.app_context import (
    FrontendAppContext as _FrontendAppContextBase,
)
from multiprocess_prototype.frontend.managers.recipe_manager_protocol import RecipeManagerProtocol
from multiprocess_prototype.frontend.managers.settings_profile_protocol import (
    SettingsProfileManagerProtocol,
)


@dataclass
class AppFrontendContext(_FrontendAppContextBase):
    """
    Доменный DI-контейнер для Inspector Bottles.

    Расширяет generic FrontendAppContext доменными полями:
    registers_manager, camera_callbacks_map, camera_type, recipe_manager,
    settings_profile_manager, command_handler и т.д.
    """

    # Переопределяем config чтобы сохранить обратную совместимость с Dict[str, Any]
    config: Dict[str, Any] = field(default_factory=dict)
    registers_manager: Optional[Any] = None
    camera_callbacks_map: Dict[str, Any] = field(default_factory=dict)
    camera_type: str = ""
    recipe_manager: Optional[RecipeManagerProtocol] = None
    settings_profile_manager: Optional[SettingsProfileManagerProtocol] = None
    command_handler: Optional[Any] = None
    camera_registry: Optional[Any] = None
    action_bus: Optional[Any] = None
    topology_editor: Optional[Any] = None  # SystemTopologyEditor — центральная модель конфигурации
    topology_bridge: Optional[Any] = None  # TopologyBridge — bridge для отправки topology на бэкенд

    def get_recipes_tab_ui(self) -> Any:
        """Section from build_frontend_config / FrontendConfig.build_dict (recipes tab texts + indices)."""
        return self.config.get("recipes_tab")

    def get_settings_tab_ui(self) -> Any:
        return self.config.get("settings_tab")

    def get_cropped_regions_tab_ui(self) -> Any:
        return self.config.get("cropped_regions_tab")

    def get_post_processing_tab_ui(self) -> Any:
        return self.config.get("post_processing_tab")

    def get_touch_keyboard(self) -> Any:
        """Секция touch_keyboard из FrontendConfig.build_dict (dict или None)."""
        return self.config.get("touch_keyboard")

    def get_camera_tab_ui(self) -> Any:
        return self.config.get("camera_tab")

    def get_recipe_access(self) -> Any:
        """Recipe field visibility / edit policy dict (merged in build_dict from app_cfg)."""
        return self.config.get("recipe_access")

    def get_processing_tab_ui(self) -> Any:
        """Optional processing tab UI dict for app-recipe aggregate (may be None if not in config)."""
        return self.config.get("processing_tab_ui")

    def get_settings_profile_tab_ui(self) -> Any:
        """Секция конфига панели профилей настроек (Phase 2)."""
        return self.config.get("settings_profile_tab")

    def get_settings_profiles_path(self) -> Any:
        """Путь к YAML профилей настроек приложения (Phase 0)."""
        return self.config.get("settings_profiles_path")

    def get_action_bus(self) -> Optional[Any]:
        """ActionBus для выполнения действий с undo/redo (или None если не инициализирован)."""
        return self.action_bus


# Alias для обратной совместимости — старый код использует FrontendAppContext
FrontendAppContext = AppFrontendContext
