"""adapters — конкретные адаптеры StateStore для prototype Inspector.

Публичный API:
    CameraStateAdapter    -- адаптер камер (cameras.*.state.**), наследует StateAdapterBase
    RegistersStateAdapter -- двунаправленный мост RegistersManager <-> StateProxy, наследует StateAdapterBase
    ServiceStateAdapter   -- двусторонняя sync ServiceRegistry <-> state.services.*, наследует StateAdapterBase
    RecipeAdapter         -- утилитный wrapper над RecipeEngine (НЕ StateAdapter)

Импорт:
    from multiprocess_prototype.backend.state.adapters import (
        CameraStateAdapter,
        RegistersStateAdapter,
        ServiceStateAdapter,
        RecipeAdapter,
    )
"""

from .camera_state_adapter import CameraStateAdapter
from .recipe_adapter import RecipeAdapter
from .registers_adapter import RegistersStateAdapter
from .service_state_adapter import ServiceStateAdapter

__all__ = [
    "CameraStateAdapter",
    "RegistersStateAdapter",
    "ServiceStateAdapter",
    "RecipeAdapter",
]
