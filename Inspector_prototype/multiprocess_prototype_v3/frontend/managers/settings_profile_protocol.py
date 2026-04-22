"""Protocol `SettingsProfileManager` — контракт для FrontendAppContext (Phase 0)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SettingsProfileManagerProtocol(Protocol):
    """Контракт менеджера профилей настроек.

    Используется `FrontendAppContext` — зависит от Protocol, а не от конкретного класса
    (как `RecipeManagerProtocol` у `RecipeManager`).
    """

    def list_profiles(self) -> list[str]: ...

    def get_profile_snapshot(self, profile_id: str) -> dict[str, Any] | None: ...

    def save_profile_snapshot(self, profile_id: str, snapshot: dict[str, Any]) -> bool: ...

    def switch_profile(self, profile_id: str, registers_bridge: Any) -> bool: ...

    def ensure_default_profile(self, registers_bridge: Any) -> None: ...

    def get_current_profile_id(self) -> str: ...

    def set_current_profile_id(self, profile_id: str) -> bool: ...
