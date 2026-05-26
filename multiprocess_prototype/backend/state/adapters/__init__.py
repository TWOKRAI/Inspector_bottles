"""adapters — конкретные адаптеры StateStore для prototype Inspector.

Публичный API:
    CameraStateAdapter    -- адаптер камер (cameras.*.state.**), наследует StateAdapterBase
    RegistersStateAdapter -- двунаправленный мост RegistersManager <-> StateProxy, наследует StateAdapterBase
    ServiceStateAdapter   -- двусторонняя sync ServiceRegistry <-> state.services.*, наследует StateAdapterBase
    DisplayStateAdapter   -- двусторонняя sync DisplayRegistry <-> state.displays.*, наследует StateAdapterBase
    RecipeStateAdapter    -- двусторонняя sync RecipeManager <-> state.recipes.*, наследует StateAdapterBase

Импорт:
    from multiprocess_prototype.backend.state.adapters import (
        CameraStateAdapter,
        RegistersStateAdapter,
        ServiceStateAdapter,
        DisplayStateAdapter,
        RecipeStateAdapter,
    )

Breaking change (Task 5.5): RecipeAdapter (slot-based wrapper) удалён, заменён на RecipeStateAdapter.
GUI-виджеты tabs/recipes/ будут обновлены в Task 5.7.
"""

from .camera_state_adapter import CameraStateAdapter
from .display_state_adapter import DisplayStateAdapter
from .recipe_adapter import RecipeStateAdapter
from .registers_adapter import RegistersStateAdapter
from .service_state_adapter import ServiceStateAdapter

__all__ = [
    "CameraStateAdapter",
    "RegistersStateAdapter",
    "ServiceStateAdapter",
    "DisplayStateAdapter",
    "RecipeStateAdapter",
]
