"""
default_bus_factory — фабрика ActionBus со стандартными handlers.

Создаётся один раз при инициализации frontend и прокидывается через FrontendAppContext.
"""

from __future__ import annotations

from .bus import ActionBus
from .handlers.chain_handler import ChainActionHandler
from .handlers.display_handler import DisplayActionHandler
from .handlers.field_set_handler import FieldSetHandler
from .handlers.profile_handler import ProfileSwitchHandler
from .handlers.recipe_handler import RecipeSwitchHandler
from .handlers.region_handler import RegionActionHandler
from .schemas import ActionType


def create_default_action_bus(rm) -> ActionBus:
    """
    Создать ActionBus с зарегистрированными стандартными handlers.

    Args:
        rm: RegistersManager (IRegistersManagerGui) или None в тестах.

    Returns:
        ActionBus с handlers для FIELD_SET, REGION_*, STEP_*, DISPLAY_*,
        PROFILE_SWITCH, RECIPE_SWITCH.
    """
    bus = ActionBus(rm)
    bus.register_handler(ActionType.FIELD_SET, FieldSetHandler())

    # Обработчик регионов (add / remove)
    region_handler = RegionActionHandler()
    bus.register_handler(ActionType.REGION_ADD, region_handler)
    bus.register_handler(ActionType.REGION_REMOVE, region_handler)

    # Обработчик шагов цепочки (add / remove / modify / reorder)
    chain_handler = ChainActionHandler()
    bus.register_handler(ActionType.STEP_ADD, chain_handler)
    bus.register_handler(ActionType.STEP_REMOVE, chain_handler)
    bus.register_handler(ActionType.STEP_MODIFY, chain_handler)
    bus.register_handler(ActionType.STEP_REORDER, chain_handler)

    # Display-подписки и раскладки (display_router подключается позже)
    display_handler = DisplayActionHandler()
    bus.register_handler(ActionType.DISPLAY_SUBSCRIBE, display_handler)
    bus.register_handler(ActionType.DISPLAY_UNSUBSCRIBE, display_handler)
    bus.register_handler(ActionType.LAYOUT_CHANGE, display_handler)

    # Профили и рецепты
    bus.register_handler(ActionType.PROFILE_SWITCH, ProfileSwitchHandler())
    bus.register_handler(ActionType.RECIPE_SWITCH, RecipeSwitchHandler())

    return bus
