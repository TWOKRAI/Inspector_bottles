# multiprocess_prototype_v3/frontend/app_context.py
"""
Явный контекст зависимостей вкладок и окон прототипа.

Один объект вместо длинного списка аргументов у create_tab_widget_factory; слои (launcher,
FrontendManager, MVP) не сливаются — меняется только способ передачи ссылок.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from multiprocess_prototype_v3.frontend.managers.recipe_manager_protocol import RecipeManagerProtocol
from multiprocess_prototype_v3.frontend.managers.settings_profile_protocol import (
    SettingsProfileManagerProtocol,
)


@dataclass
class FrontendAppContext:
    """
    Снимок зависимостей, нужных фабрике вкладок и (при необходимости) другим хелперам UI.

    Attributes:
        config: dict после FrontendConfig.build_dict (вкладки, recipe_access, ui_diagnostics, …).
        registers_manager: мост/менеджер регистров с процесса (или None в тестах).
        camera_callbacks_map: колбэки камеры (уже собранные из GuiCommandHandler).
        camera_type: режим камеры для CameraTabWidget.
        recipe_manager: менеджер YAML рецептов (или None).
        settings_profile_manager: менеджер профилей настроек приложения (Phase 0, или None).
        command_handler: GuiCommandHandler — для будущих вкладок / диагностики; сейчас колбэки
            камеры уже замкнуты на него в launcher.
        Методы ``get_*_tab_ui`` / ``get_recipe_access``: стабильные ключи секций ``config`` для
        фабрики вкладок (см. ``FrontendConfig.build_dict``), включая ``get_post_processing_tab_ui``.
    """

    config: Dict[str, Any]
    registers_manager: Optional[Any]
    camera_callbacks_map: Dict[str, Any]
    camera_type: str
    recipe_manager: Optional[RecipeManagerProtocol] = None
    settings_profile_manager: Optional[SettingsProfileManagerProtocol] = None
    command_handler: Optional[Any] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def get_recipes_tab_ui(self) -> Any:
        """Section from `build_frontend_config` / `FrontendConfig.build_dict` (recipes tab texts + indices)."""
        return self.config.get("recipes_tab")

    def get_settings_tab_ui(self) -> Any:
        return self.config.get("settings_tab")

    def get_cropped_regions_tab_ui(self) -> Any:
        return self.config.get("cropped_regions_tab")

    def get_post_processing_tab_ui(self) -> Any:
        return self.config.get("post_processing_tab")

    def get_touch_keyboard(self) -> Any:
        """Секция ``touch_keyboard`` из ``FrontendConfig.build_dict`` (dict или None)."""
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
