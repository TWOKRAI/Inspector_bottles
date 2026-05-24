"""adapters -- адаптеры для интеграции StateStore с доменной логикой.

Публичный API:
    IStateAdapter     -- runtime_checkable Protocol (контракт адаптера)
    StateAdapterBase  -- ABC базовый класс для конкретных адаптеров
"""

from .base import IStateAdapter, StateAdapterBase

__all__ = ["IStateAdapter", "StateAdapterBase"]
