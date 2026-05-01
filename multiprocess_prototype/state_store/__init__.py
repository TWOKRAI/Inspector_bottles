"""state_store — доменная точка входа для прикладного слоя.

Реализация перенесена в `multiprocess_framework.modules.state_store_module`.
Здесь оставлены только доменные компоненты:
    bootstrap.py        — построение начального дерева состояния из AppConfig
    adapters/           — доменные адаптеры (camera_state, registers, recipe)
    recipes/recipe_engine — wrapper над generic-RecipeEngine с подключением
                            доменных миграций v1→v2 (см. recipes/migrations/)

Публичный API generic-классов реэкспортирован из фреймворка для
обратной совместимости (адаптеры и прикладной код прототипа используют
короткие импорты из `multiprocess_prototype.state_store`).
"""
from multiprocess_framework.modules.state_store_module import (
    TreeStore,
    Delta,
    Transaction,
    MISSING,
    SubscriptionManager,
    Subscription,
    StateStoreManager,
    DeltaDispatcher,
    StateProxy,
    GuiStateProxy,
    StateMiddleware,
    MiddlewarePipeline,
    ThrottleMiddleware,
    ValidationMiddleware,
    LoggingMiddleware,
    MetricsMiddleware,
    Selector,
    SelectorRegistry,
)

# Доменный wrapper RecipeEngine (подключает миграцию v1→v2 автоматически)
from multiprocess_prototype.state_store.recipes.recipe_engine import RecipeEngine

__all__ = [
    "TreeStore",
    "Delta",
    "Transaction",
    "MISSING",
    "SubscriptionManager",
    "Subscription",
    "StateStoreManager",
    "DeltaDispatcher",
    "StateProxy",
    "GuiStateProxy",
    "StateMiddleware",
    "MiddlewarePipeline",
    "ThrottleMiddleware",
    "ValidationMiddleware",
    "LoggingMiddleware",
    "MetricsMiddleware",
    "RecipeEngine",
    "Selector",
    "SelectorRegistry",
]
