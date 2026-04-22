"""Фабрика ComboModel для строковых профилей настроек (Phase 2, Task 2.2).

Переиспользует `RecipeSlotComboModel` без дублирования — строит из
`SettingsProfileManager.list_profiles()` с `label_fn = lambda pid: pid`.
"""

from __future__ import annotations

from typing import Any

from ..recipes_widget.slot_combo_model import RecipeSlotComboModel

_DEFAULT_PROFILE_ID = "default"


def from_profile_manager(manager: Any) -> RecipeSlotComboModel:
    """Построить ComboModel из `SettingsProfileManager.list_profiles()`.

    Если менеджер None или список пуст — fallback на ``["default"]``.
    """
    profiles: list[str] = []
    if manager is not None and hasattr(manager, "list_profiles"):
        try:
            found = manager.list_profiles()
        except Exception:
            found = None
        if isinstance(found, list) and found:
            profiles = [str(p) for p in found]
    if not profiles:
        profiles = [_DEFAULT_PROFILE_ID]
    return RecipeSlotComboModel(
        slots=profiles,
        current_index=0,
        label_fn=lambda pid: pid,
    )


def sync_current(model: RecipeSlotComboModel, manager: Any) -> None:
    """Синхронизировать `current_index` модели с текущим профилем менеджера."""
    if manager is None or not hasattr(manager, "get_current_profile_id"):
        return
    try:
        current_id = manager.get_current_profile_id()
    except Exception:
        return
    model.current_index = model.index_for_slot_id(str(current_id))


def profile_id_from_model(model: RecipeSlotComboModel) -> str:
    """Текущий profile_id (str) из модели — замена `parse_slot() -> int` для профилей."""
    return model.current_slot_id()


__all__ = ["from_profile_manager", "sync_current", "profile_id_from_model"]
