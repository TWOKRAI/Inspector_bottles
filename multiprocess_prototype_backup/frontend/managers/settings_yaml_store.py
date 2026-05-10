"""SettingsYamlStore — тонкий subclass YamlPersistenceStore для профилей настроек Inspector Bottles.

Инициализирует базовый store с доменными зависимостями:
- default_snapshot_factory: AppSettingsRegisters().model_dump()
- from_dict: AppSettingsRegisters.model_validate
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.frontend_module.managers import YamlPersistenceStore
from multiprocess_prototype.config.settings_profile import SettingsProfile
from multiprocess_prototype.registers.settings import AppSettingsRegisters

_PROTO_ROOT = Path(__file__).resolve().parent.parent.parent

SETTINGS_FILE_VERSION = 1
DEFAULT_PROFILE_ID = "default"


def default_settings_profiles_path() -> Path:
    """Путь к data/settings_profiles.yaml относительно корня прототипа."""
    return _PROTO_ROOT / "data" / "settings_profiles.yaml"


def default_profile_snapshot() -> dict:
    """Заводской снимок профиля: дефолты AppSettingsRegisters."""
    return AppSettingsRegisters().model_dump()


class SettingsYamlStore(YamlPersistenceStore[SettingsProfile]):
    """YAML-backed persistence для профилей настроек приложения."""

    def __init__(self, file_path: Path | None = None) -> None:
        super().__init__(
            file_path or default_settings_profiles_path(),
            default_snapshot_factory=default_profile_snapshot,
            from_dict=AppSettingsRegisters.model_validate,
        )


__all__ = [
    "SETTINGS_FILE_VERSION",
    "DEFAULT_PROFILE_ID",
    "SettingsYamlStore",
    "default_settings_profiles_path",
    "default_profile_snapshot",
]
