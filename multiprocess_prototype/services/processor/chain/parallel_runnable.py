"""Параллельный executor цепочки обработки.

Re-export из multiprocess_framework.modules.chain_module (Phase 2.3).
"""
from multiprocess_framework.modules.chain_module import ParallelChainRunnable

__all__ = ["ParallelChainRunnable"]
