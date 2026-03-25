# multiprocess_prototype/managers/recipe_manager_protocol.py
"""Structural typing for YAML recipe I/O used by register/app recipe panels."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Union, runtime_checkable

RecipeSlotId = Union[int, str]


@runtime_checkable
class RecipeManagerProtocol(Protocol):
    """
    Contract implemented by RecipeManager for register + app recipe slots.

    Panels use this Protocol instead of Any for recipe_manager injection.
    """

    def get_current_register_recipe_number(self) -> int: ...

    def set_current_register_recipe_number(self, number: int) -> None: ...

    def load_recipe_to_registers(self, registers_bridge: Any, recipe_id: RecipeSlotId) -> bool: ...

    def save_registers_to_recipe(self, registers_bridge: Any, recipe_id: RecipeSlotId) -> bool: ...

    def get_current_app_recipe_number(self) -> int: ...

    def set_current_app_recipe_number(self, number: int) -> None: ...

    def load_app_recipe_snapshot(self, recipe_id: RecipeSlotId) -> Optional[Dict[str, Any]]: ...

    def save_app_recipe_snapshot(self, recipe_id: RecipeSlotId, snapshot: Dict[str, Any]) -> bool: ...
