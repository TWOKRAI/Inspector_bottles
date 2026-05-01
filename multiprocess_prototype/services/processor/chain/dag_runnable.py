"""Исполняемый DAG (направленный ацикличный граф) обработки кадра.

Re-export из multiprocess_framework.modules.chain_module (Phase 2.3).
"""
from multiprocess_framework.modules.chain_module import DagRunnable

__all__ = ["DagRunnable"]
