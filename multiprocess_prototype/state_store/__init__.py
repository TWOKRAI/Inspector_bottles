# state_store — реактивное хранилище данных для Inspector
#
# Публичный API:
#   TreeStore — иерархическое dict-хранилище с путевым доступом
#   Delta — единица изменения (иммутабельный dataclass)
#   Transaction — группировка нескольких Delta в batch
#   MISSING — sentinel для отсутствующего значения
#   SubscriptionManager — управление подписками с glob-style matching
#   Subscription — описание одной подписки
from multiprocess_prototype.state_store.core.delta import MISSING, Delta, Transaction
from multiprocess_prototype.state_store.core.subscription_manager import Subscription, SubscriptionManager
from multiprocess_prototype.state_store.core.tree_store import TreeStore
from multiprocess_prototype.state_store.manager.delta_dispatcher import DeltaDispatcher
from multiprocess_prototype.state_store.manager.state_store_manager import StateStoreManager
from multiprocess_prototype.state_store.middleware.base import MiddlewarePipeline, StateMiddleware
from multiprocess_prototype.state_store.middleware.logging_mw import LoggingMiddleware
from multiprocess_prototype.state_store.middleware.metrics import MetricsMiddleware
from multiprocess_prototype.state_store.middleware.throttle import ThrottleMiddleware
from multiprocess_prototype.state_store.middleware.validation import ValidationMiddleware
from multiprocess_prototype.state_store.proxy.gui_state_proxy import GuiStateProxy
from multiprocess_prototype.state_store.proxy.state_proxy import StateProxy
from multiprocess_prototype.state_store.recipes.recipe_engine import RecipeEngine
from multiprocess_prototype.state_store.selectors.selector import Selector, SelectorRegistry

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
