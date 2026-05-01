"""Исполняемая цепочка обработки кадра.

Re-export из multiprocess_framework.modules.chain_module (Phase 2.3).
"""
from multiprocess_framework.modules.chain_module import (
    ChainResult,
    ChainRunnable,
    IRunnableChain,
    RunnableStep,
)
from multiprocess_framework.modules.chain_module.core.result import (
    _collect_side_results,
    _is_cross_process,
)

__all__ = [
    "ChainRunnable",
    "ChainResult",
    "IRunnableChain",
    "RunnableStep",
    "_collect_side_results",
    "_is_cross_process",
]
