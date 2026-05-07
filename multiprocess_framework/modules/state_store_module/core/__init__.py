"""core — Ядро state_store_module: дерево состояния, дельты, подписки.

Публичный API:
    TreeStore           — иерархическое dict-хранилище с путевым доступом
    Delta               — иммутабельная единица изменения
    Transaction         — batch-группировка дельт с единым transaction_id
    MISSING             — sentinel для отсутствующего значения
    SubscriptionManager — управление подписками с glob-style matching
    Subscription        — описание одной подписки
    match_pattern       — публичный алиас для glob-матчинга паттерна с путём (ADR-SS-004)
    split_pattern       — публичный алиас для кэшированного split паттерна (ADR-SS-004)
    iter_matches        — обход дерева по glob-паттерну (генератор пар path/value)
"""
from .delta import Delta, MISSING, Transaction
from .tree_store import TreeStore
from .subscription_manager import SubscriptionManager, Subscription, match_pattern, split_pattern
from .glob_walker import iter_matches

__all__ = [
    "TreeStore",
    "Delta",
    "Transaction",
    "MISSING",
    "SubscriptionManager",
    "Subscription",
    "match_pattern",
    "split_pattern",
    "iter_matches",
]
