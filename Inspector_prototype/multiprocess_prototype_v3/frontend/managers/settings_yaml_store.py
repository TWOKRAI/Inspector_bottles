"""SettingsYamlStore — YAML-хранилище профилей настроек (Phase 0, Task 0.2).

Зеркало паттерна YAML-read/write из ``RecipeManager``, выделенное в изолированный класс:
менеджер профилей (Task 0.3) использует его для persistence, а сам store тестируется
отдельно от бизнес-логики.

Формат файла::

    version: 1
    current_profile: "default"
    profiles:
      default:
        camera_count: 1
        ring_buffer_size: 3
        ...
      fast:
        camera_count: 4
        ...
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from multiprocess_prototype_v3.registers.settings import AppSettingsRegisters

SETTINGS_FILE_VERSION = 1
DEFAULT_PROFILE_ID = "default"

_PROTO_ROOT = Path(__file__).resolve().parent.parent.parent


def default_settings_profiles_path() -> Path:
    """Путь к `data/settings_profiles.yaml` относительно корня прототипа."""
    return _PROTO_ROOT / "data" / "settings_profiles.yaml"


def default_profile_snapshot() -> dict[str, Any]:
    """Заводской снимок профиля: дефолты ``AppSettingsRegisters``."""
    return AppSettingsRegisters().model_dump()


class SettingsYamlStore:
    """YAML-backed persistence для профилей настроек приложения."""

    def __init__(self, data_path: str | None = None) -> None:
        self._path = Path(data_path) if data_path else default_settings_profiles_path()

    @property
    def path(self) -> Path:
        return self._path

    def read_dict(self) -> dict[str, Any] | None:
        """Прочитать YAML; ``None`` если файла нет или битый."""
        if not self._path.is_file():
            return None
        try:
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def save(
        self,
        *,
        version: int = SETTINGS_FILE_VERSION,
        current_profile: str = DEFAULT_PROFILE_ID,
        profiles: dict[str, dict[str, Any]],
    ) -> bool:
        """Записать профили в YAML (создаёт директорию при необходимости)."""
        payload: dict[str, Any] = {
            "version": version,
            "current_profile": current_profile,
            "profiles": copy.deepcopy(profiles),
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.safe_dump(payload, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            return True
        except OSError:
            return False


__all__ = [
    "SETTINGS_FILE_VERSION",
    "DEFAULT_PROFILE_ID",
    "SettingsYamlStore",
    "default_settings_profiles_path",
    "default_profile_snapshot",
]
