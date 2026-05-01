"""Управление пулом потоков для параллельного исполнения шагов chain.

Re-export из multiprocess_framework.modules.chain_module (Phase 2.3).
"""
from multiprocess_framework.modules.chain_module import ChainThreadPool

__all__ = ["ChainThreadPool"]
