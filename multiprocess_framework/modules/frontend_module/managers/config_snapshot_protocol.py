# frontend_module/managers/config_snapshot_protocol.py
"""Structural typing для YAML-хранилища именованных снимков конфигурации."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Union, runtime_checkable

RecipeSlotId = Union[int, str]


@runtime_checkable
class RecipeManagerProtocol(Protocol):
    """
    Контракт менеджера снимков конфигурации (register + app slots).

    Панели используют этот Protocol вместо Any для внедрения recipe_manager.
    """

    def get_current_register_recipe_number(self) -> int: ...

    def set_current_register_recipe_number(self, number: int) -> None: ...

    def load_recipe_to_registers(self, registers_bridge: Any, recipe_id: RecipeSlotId) -> bool: ...

    def save_registers_to_recipe(self, registers_bridge: Any, recipe_id: RecipeSlotId) -> bool: ...

    def get_current_app_recipe_number(self) -> int: ...

    def set_current_app_recipe_number(self, number: int) -> None: ...

    def load_app_recipe_snapshot(self, recipe_id: RecipeSlotId) -> Optional[Dict[str, Any]]: ...

    def save_app_recipe_snapshot(self, recipe_id: RecipeSlotId, snapshot: Dict[str, Any]) -> bool: ...

    # Register-recipe snapshot API (для превью слота без записи в registers)
    def list_slots(self) -> list[str]: ...

    def get_slot(self, slot_id: str) -> Optional[Dict[str, Any]]: ...

    def save_slot(self, slot_id: str, data: Dict[str, Any]) -> bool: ...


# Alias для использования в generic-коде фреймворка
ConfigSnapshotProtocol = RecipeManagerProtocol

__all__ = ["RecipeManagerProtocol", "ConfigSnapshotProtocol", "RecipeSlotId"]
