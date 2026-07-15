"""Пул кадровых слотов SHM с владением по цепочке (Ф7 H-задача, консолидация памяти).

Фасад: `FramePool` (Protocol) + `LoanLedger` (реализация руками на CPython). Транспорт
(`FrameShmMiddleware`) держит пул через DI и делегирует — семантика владения слотом
(loan/publish/release/reclaim) больше не размазана по router-модулю. Контракт 1:1 с
iceoryx2/DDS → замена на Rust-транспорт = новая реализация под тем же Protocol.
"""

from .interfaces import FramePool, GenerationReader, LoanTicket, PoolStats
from .loan_ledger import LoanLedger

__all__ = ["FramePool", "LoanLedger", "LoanTicket", "PoolStats", "GenerationReader"]
