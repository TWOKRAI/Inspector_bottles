"""interfaces.py — публичные контракты chain_module.

Протоколы для структурной типизации: chain_module не импортирует доменный код,
доменные классы прототипа реализуют эти протоколы неявно (duck-typing).

    IStepNode        — минимальный контракт дескриптора ноды (node_id, operation_ref, inputs)
    INodeConnection  — соединение между нодами (source, input_port, output_port)
    IExecutionStep   — операция обработки (execute, configure)
    IChainRunnable   — исполняемая цепочка (execute → ChainResult)
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class INodeConnection(Protocol):
    """Соединение между двумя нодами графа обработки."""

    source: str
    input_port: str
    output_port: str


@runtime_checkable
class IStepNode(Protocol):
    """Минимальный контракт дескриптора ноды для chain execution."""

    node_id: str
    operation_ref: str
    inputs: list  # элементы реализуют INodeConnection


@runtime_checkable
class IStepNodeWithWorker(IStepNode, Protocol):
    """Дескриптор ноды с поддержкой worker-affinity (для параллельных бандлов)."""

    worker_id: str | None


@runtime_checkable
class IExecutionStep(Protocol):
    """Операция обработки: принимает данные + контекст, возвращает данные."""

    def execute(self, data: Any, context: Any) -> Any:
        """Обработать входные данные, вернуть результат."""
        ...

    def configure(self, params: dict) -> None:
        """Настроить параметры операции."""
        ...


@runtime_checkable
class IChainRunnable(Protocol):
    """Протокол исполняемой цепочки обработки."""

    def execute(self, frame: Any, metadata: dict | None = None) -> Any:
        """Исполнить цепочку, вернуть ChainResult."""
        ...


__all__ = [
    "INodeConnection",
    "IStepNode",
    "IStepNodeWithWorker",
    "IExecutionStep",
    "IChainRunnable",
]
