"""Протокол обмена данными между Processor и Worker-процессами.

Re-export из multiprocess_framework.modules.chain_module (Phase 2.3).
"""
from multiprocess_framework.modules.chain_module import WorkerTaskRequest, WorkerTaskResponse

__all__ = ["WorkerTaskRequest", "WorkerTaskResponse"]
