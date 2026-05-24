"""adapters — конкретные адаптеры StateStore для prototype Inspector.

Публичный API:
    CameraStateAdapter   -- адаптер камер (cameras.*.state.**), наследует StateAdapterBase
    RegistersStateAdapter -- двунаправленный мост RegistersManager <-> StateProxy, наследует StateAdapterBase
    RecipeAdapter        -- утилитный wrapper над RecipeEngine (НЕ StateAdapter)

Импорт:
    from multiprocess_prototype.backend.state.adapters import (
        CameraStateAdapter,
        RegistersStateAdapter,
        RecipeAdapter,
    )
"""

from .camera_state_adapter import CameraStateAdapter
from .recipe_adapter import RecipeAdapter
from .registers_adapter import RegistersStateAdapter

__all__ = [
    "CameraStateAdapter",
    "RegistersStateAdapter",
    "RecipeAdapter",
]
