"""SettingsProfileManager — менеджер профилей настроек приложения (Phase 0, Task 0.3).

Зеркало `RecipeManager` для профилей настроек:
- persistence через `SettingsYamlStore`;
- валидация снимка через `AppSettingsRegisters.model_validate`;
- SHM-budget check (AD-6) при switch/save;
- применение профиля в `RegistersManager` через `model_validate_all`.
"""

from __future__ import annotations

import copy
from typing import Any

from multiprocess_prototype.registers.constants import SETTINGS_REGISTER
from multiprocess_prototype.registers.settings import AppSettingsRegisters

from .settings_yaml_store import (
    DEFAULT_PROFILE_ID,
    SettingsYamlStore,
    default_profile_snapshot,
)

# AD-6: worst-case BGR slot для budget-check — 1080p (3 байта на пиксель).
_FRAME_BYTES_1080P_BGR = 1920 * 1080 * 3
_BYTES_PER_MB = 1024 * 1024


class ShmBudgetError(Exception):
    """Превышение SHM-бюджета профилем (AD-6)."""

    def __init__(
        self,
        *,
        camera_count: int,
        ring_buffer_size: int,
        required_mb: float,
        budget_mb: int,
    ) -> None:
        self.camera_count = camera_count
        self.ring_buffer_size = ring_buffer_size
        self.required_mb = required_mb
        self.budget_mb = budget_mb
        super().__init__(
            f"SHM budget exceeded: {camera_count} cam × K={ring_buffer_size} × 1080p BGR "
            f"= {required_mb:.1f} MB > budget {budget_mb} MB",
        )


def validate_shm_budget(profile: AppSettingsRegisters) -> None:
    """Проверка SHM-бюджета профиля (AD-6). Поднимает `ShmBudgetError` при превышении."""
    required_bytes = profile.camera_count * profile.ring_buffer_size * _FRAME_BYTES_1080P_BGR
    required_mb = required_bytes / _BYTES_PER_MB
    if required_mb > profile.shm_budget_mb:
        raise ShmBudgetError(
            camera_count=profile.camera_count,
            ring_buffer_size=profile.ring_buffer_size,
            required_mb=required_mb,
            budget_mb=profile.shm_budget_mb,
        )


class SettingsProfileManager:
    """YAML-backed менеджер профилей настроек + мост в `RegistersManager`."""

    def __init__(self, data_path: str | None = None) -> None:
        from pathlib import Path
        self._store = SettingsYamlStore(file_path=Path(data_path) if data_path else None)
        self._profiles: dict[str, dict[str, Any]] = {}
        self._current_profile_id: str = DEFAULT_PROFILE_ID
        self._load()

    # ---- Persistence ------------------------------------------------------

    def _load(self) -> None:
        data = self._store.read_dict()
        if data is None:
            self._profiles = {}
            self._current_profile_id = DEFAULT_PROFILE_ID
            return
        profiles = data.get("profiles") or {}
        if isinstance(profiles, dict):
            self._profiles = {k: dict(v) for k, v in profiles.items() if isinstance(v, dict)}
        current = data.get("current_profile")
        self._current_profile_id = current if isinstance(current, str) else DEFAULT_PROFILE_ID

    def _save(self) -> bool:
        return self._store.save(
            current_profile=self._current_profile_id,
            profiles=self._profiles,
        )

    # ---- Public API -------------------------------------------------------

    def list_profiles(self) -> list[str]:
        return list(self._profiles.keys())

    def get_profile_snapshot(self, profile_id: str) -> dict[str, Any] | None:
        snap = self._profiles.get(profile_id)
        return copy.deepcopy(snap) if snap is not None else None

    def save_profile_snapshot(self, profile_id: str, snapshot: dict[str, Any]) -> bool:
        """Валидировать снимок через схему и записать в слот (deepcopy)."""
        validated = AppSettingsRegisters.model_validate(snapshot).model_dump()
        self._profiles[profile_id] = validated
        return self._save()

    def get_current_profile_id(self) -> str:
        return self._current_profile_id

    def set_current_profile_id(self, profile_id: str) -> bool:
        """Зафиксировать «текущий» профиль в YAML (без применения в регистры)."""
        if profile_id not in self._profiles:
            return False
        self._current_profile_id = profile_id
        return self._save()

    def switch_profile(self, profile_id: str, registers_bridge: Any) -> bool:
        """Применить профиль в регистры (`model_validate_all`) + зафиксировать как текущий.

        Returns:
            True — профиль найден и применён.
            False — слот не существует.

        Raises:
            ShmBudgetError — если профиль превышает SHM-бюджет (AD-6).
        """
        snap = self._profiles.get(profile_id)
        if snap is None:
            return False
        profile = AppSettingsRegisters.model_validate(snap)
        validate_shm_budget(profile)
        registers_bridge.model_validate_all({SETTINGS_REGISTER: profile.model_dump()})
        self._current_profile_id = profile_id
        self._save()
        return True

    def ensure_default_profile(self, registers_bridge: Any) -> None:
        """Гарантировать наличие слота "default" (заводские дефолты) + применить его.

        Идемпотентно: если слот уже есть — ничего не создаёт, только применяет.
        """
        if DEFAULT_PROFILE_ID not in self._profiles:
            self._profiles[DEFAULT_PROFILE_ID] = default_profile_snapshot()
            self._current_profile_id = DEFAULT_PROFILE_ID
            self._save()
        snap = self._profiles[DEFAULT_PROFILE_ID]
        registers_bridge.model_validate_all({SETTINGS_REGISTER: dict(snap)})


__all__ = [
    "ShmBudgetError",
    "SettingsProfileManager",
    "validate_shm_budget",
]
