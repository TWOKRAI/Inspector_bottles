# state_store — реактивное хранилище данных для Inspector
#
# Публичный API:
#   TreeStore — иерархическое dict-хранилище с путевым доступом
#   Delta — единица изменения (иммутабельный dataclass)
#   Transaction — группировка нескольких Delta в batch
#   MISSING — sentinel для отсутствующего значения
#   SubscriptionManager — управление подписками с glob-style matching
#   Subscription — описание одной подписки
from state_store.core.delta import MISSING, Delta, Transaction
from state_store.core.subscription_manager import Subscription, SubscriptionManager
from state_store.core.tree_store import TreeStore
from state_store.manager.delta_dispatcher import DeltaDispatcher
from state_store.manager.state_store_manager import StateStoreManager
from state_store.proxy.state_proxy import StateProxy
from state_store.proxy.gui_state_proxy import GuiStateProxy

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
]
