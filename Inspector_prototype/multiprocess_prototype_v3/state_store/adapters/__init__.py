"""state_store.adapters — адаптеры для интеграции StateStore с внешними системами."""

from state_store.adapters.camera_state_adapter import CameraStateAdapter
from state_store.adapters.recipe_adapter import RecipeAdapter
from state_store.adapters.registers_adapter import RegistersStateAdapter

__all__ = ["CameraStateAdapter", "RecipeAdapter", "RegistersStateAdapter"]
