"""chain_module — DAG/Chain execution engine для многопроцессных приложений.

Публичный API:

    Контракты (interfaces.py):
        IStepNode           — дескриптор ноды (node_id, operation_ref, inputs)
        IStepNodeWithWorker — нода с worker-affinity (worker_id)
        INodeConnection     — соединение между нодами (source, input_port, output_port)
        IExecutionStep      — операция обработки (execute, configure)
        IChainRunnable      — исполняемая цепочка (execute → ChainResult)
        IRemoteExecutable   — шаг с cross-process исполнением (execute_remote)
        IChainLogger        — узкий публичный логгер исполнителей (log_info/warning/error)

    Контекст / Результат:
        ChainContext        — контекст выполнения (IDs, warnings, errors, timeouts)
        ChainResult         — результат цепочки (frame, detections, timing)
        RunnableStep        — шаг: нода + операция + on_error политика

    Исполнители:
        ChainRunnable       — последовательная цепочка
        DagRunnable         — DAG с ветвлениями/слияниями
        ParallelChainRunnable — параллельные бандлы через ChainThreadPool
        IRunnableChain      — Protocol для всех исполнителей

    Thread pool:
        ChainThreadPool     — пул параллельных бандлов (фасад над worker_module)
        WorkerPoolExecutor  — примитив пула поверх worker_module (N LOOP-воркеров)

    Graph utilities:
        topological_sort    — алгоритм Кана (Kahn's)
        is_nonlinear_graph  — обнаружение ветвлений/merge
        detect_parallel_bundles — разбиение на уровни для параллельности

    Worker pool (IPC):
        WorkerTaskRequest   — запрос к worker-процессу (Dict at Boundary)
        WorkerTaskResponse  — ответ от worker-процесса (Dict at Boundary)
        WorkerPoolDispatcher — round-robin маршрутизация, backpressure, timeout

    Metrics:
        LatencyTracker      — p50/p95/p99 latency с периодическим логированием
"""

from .interfaces import (
    IStepNode,
    IStepNodeWithWorker,
    INodeConnection,
    IExecutionStep,
    IChainRunnable,
    IRemoteExecutable,
    IChainLogger,
)
from .core import (
    ChainContext,
    ChainResult,
    RunnableStep,
    apply_on_error_policy,
    ChainRunnable,
    IRunnableChain,
    DagRunnable,
    ParallelChainRunnable,
)
from .thread_pool import ChainThreadPool, WorkerPoolExecutor
from .graph import topological_sort, is_nonlinear_graph, detect_parallel_bundles
from .worker_pool import WorkerTaskRequest, WorkerTaskResponse, WorkerPoolDispatcher
from .metrics import LatencyTracker

__all__ = [
    # Контракты
    "IStepNode",
    "IStepNodeWithWorker",
    "INodeConnection",
    "IExecutionStep",
    "IChainRunnable",
    "IRemoteExecutable",
    "IChainLogger",
    # Контекст / Результат
    "ChainContext",
    "ChainResult",
    "RunnableStep",
    "apply_on_error_policy",
    # Исполнители
    "ChainRunnable",
    "IRunnableChain",
    "DagRunnable",
    "ParallelChainRunnable",
    # Thread pool
    "ChainThreadPool",
    "WorkerPoolExecutor",
    # Graph
    "topological_sort",
    "is_nonlinear_graph",
    "detect_parallel_bundles",
    # Worker pool
    "WorkerTaskRequest",
    "WorkerTaskResponse",
    "WorkerPoolDispatcher",
    # Metrics
    "LatencyTracker",
]
