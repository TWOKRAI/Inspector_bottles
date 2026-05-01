"""frontend_module.managers — generic менеджеры для frontend-приложений."""

from .access_context import AccessContext
from .config_snapshot_protocol import RecipeManagerProtocol, ConfigSnapshotProtocol, RecipeSlotId
from .settings_profile_protocol import SettingsProfileManagerProtocol
from .config_snapshot_manager import ConfigSnapshotManager, DEFAULT_SNAPSHOT_SLOT_ID
from .yaml_persistence_store import YamlPersistenceStore, DEFAULT_PROFILE_ID
from .theme_manager import ThemeManager
from .theme_presets_manager import ThemePresetsManager

__all__ = [
    "AccessContext",
    "RecipeManagerProtocol", "ConfigSnapshotProtocol", "RecipeSlotId",
    "SettingsProfileManagerProtocol",
    "ConfigSnapshotManager", "DEFAULT_SNAPSHOT_SLOT_ID",
    "YamlPersistenceStore", "DEFAULT_PROFILE_ID",
    "ThemeManager",
    "ThemePresetsManager",
]
