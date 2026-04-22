"""Менеджеры уровня frontend-приложения."""

from .display_router import DisplayRouter
from .window_manager import DisplayWindowManager
from .recipe_manager import DEFAULT_RECIPE_SLOT_ID, RecipeManager
from .recipe_manager_protocol import RecipeManagerProtocol
from .settings_profile_manager import (
    SettingsProfileManager,
    ShmBudgetError,
    validate_shm_budget,
)
from .settings_profile_protocol import SettingsProfileManagerProtocol
from .settings_yaml_store import (
    DEFAULT_PROFILE_ID,
    SETTINGS_FILE_VERSION,
    SettingsYamlStore,
    default_profile_snapshot,
    default_settings_profiles_path,
)

__all__ = [
    "DEFAULT_RECIPE_SLOT_ID",
    "DEFAULT_PROFILE_ID",
    "DisplayRouter",
    "DisplayWindowManager",
    "SETTINGS_FILE_VERSION",
    "RecipeManager",
    "RecipeManagerProtocol",
    "SettingsProfileManager",
    "SettingsProfileManagerProtocol",
    "SettingsYamlStore",
    "ShmBudgetError",
    "default_profile_snapshot",
    "default_settings_profiles_path",
    "validate_shm_budget",
]
