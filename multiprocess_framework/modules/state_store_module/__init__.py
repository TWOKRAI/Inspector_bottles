"""state_store_module — реактивное дерево состояния для многопроцессных приложений.

Публичный API:
    Контракты (interfaces.py):
        IRouter             — внешняя зависимость (Protocol, ADR-SS-001)
        IStateStore         — контракт TreeStore (ABC, ADR-SS-009)
        IStateProxy         — контракт StateProxy (ABC, ADR-SS-009)
        IStateStoreManager  — контракт StateStoreManager (ABC, ADR-SS-009)

    Реализации:
        StateStoreManager  — серверный фасад (manager/)
        StateProxy         — клиентский прокси (proxy/)
        GuiStateProxy      — клиентский прокси для PySide6 GUI (proxy/)
        DeltaDispatcher    — рассылка дельт подписчикам (manager/)

    Core:
        TreeStore, Delta, Transaction, MISSING,
        SubscriptionManager, Subscription,
        match_pattern, split_pattern  — публичные хелперы для middleware/health

    Middleware:
        StateMiddleware, MiddlewarePipeline,
        ThrottleMiddleware, ValidationMiddleware,
        LoggingMiddleware, MetricsMiddleware

    Selectors / DevTools / Health / Persistence / Recipes:
        Selector, SelectorRegistry      — selectors/
        StateInspector                  — devtools/
        HealthMonitor, WatchedProcess   — health/
        PersistenceManager              — persistence/
        RecipeEngine                    — recipes/

    Testing (ADR-SS-010):
        InMemoryRouter  — mock IRouter для unit-тестов прикладного кода
"""
from .interfaces import IRouter, IStateStore, IStateProxy, IStateStoreManager
from .core import (
    TreeStore,
    Delta,
    Transaction,
    MISSING,
    SubscriptionManager,
    Subscription,
    match_pattern,
    split_pattern,
)
from .manager import StateStoreManager, DeltaDispatcher
from .proxy import StateProxy, GuiStateProxy
from .middleware import (
    StateMiddleware,
    MiddlewarePipeline,
    ThrottleMiddleware,
    ValidationMiddleware,
    LoggingMiddleware,
    MetricsMiddleware,
)
from .selectors import Selector, SelectorRegistry
from .devtools import StateInspector
from .health import HealthMonitor, WatchedProcess
from .persistence import PersistenceManager
from .recipes import RecipeEngine
from .testing import InMemoryRouter

__all__ = [
    # Контракты
    "IRouter", "IStateStore", "IStateProxy", "IStateStoreManager",
    # Реализации
    "StateStoreManager", "StateProxy", "GuiStateProxy", "DeltaDispatcher",
    # Core
    "TreeStore", "Delta", "Transaction", "MISSING",
    "SubscriptionManager", "Subscription",
    "match_pattern", "split_pattern",
    # Middleware
    "StateMiddleware", "MiddlewarePipeline",
    "ThrottleMiddleware", "ValidationMiddleware",
    "LoggingMiddleware", "MetricsMiddleware",
    # Selectors / DevTools / Health / Persistence / Recipes
    "Selector", "SelectorRegistry",
    "StateInspector",
    "HealthMonitor", "WatchedProcess",
    "PersistenceManager",
    "RecipeEngine",
    # Testing
    "InMemoryRouter",
]
