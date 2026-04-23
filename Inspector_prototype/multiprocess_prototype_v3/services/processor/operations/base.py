"""Базовые интерфейсы цепочки обработки кадров."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass
class ChainContext:
    """Контекст, передаваемый между операциями в цепочке обработки."""

    camera_id: str = ""
    region_id: str = ""
    seq_id: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timeouts: list[str] = field(default_factory=list)  # node_id зависших нод


@runtime_checkable
class ProcessingOperation(Protocol):
    """Протокол операции обработки кадра.

    Каждая операция получает кадр + контекст, возвращает обработанный кадр.
    Побочные эффекты (детекции, предупреждения) пишутся в context.
    """

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Обработать кадр, вернуть результат."""
        ...

    def configure(self, params: dict) -> None:
        """Настроить параметры операции."""
        ...


def execute_dag_default(
    operation: ProcessingOperation,
    inputs: dict[str, Any],
    context: ChainContext,
) -> dict[str, Any]:
    """DAG-обёртка для legacy-операций: берёт inputs["in"], вызывает execute(), возвращает {"out": result}.

    Если операция реализует собственный метод execute_dag — вызывается он.
    Иначе — используется стандартная обёртка над execute().

    Args:
        operation: Экземпляр операции (реализует ProcessingOperation).
        inputs: Словарь входных данных {port_name: value}.
        context: Контекст цепочки обработки.

    Returns:
        Словарь выходных данных {port_name: value}.
    """
    # Если операция поддерживает DAG-интерфейс напрямую — вызываем его
    if hasattr(operation, "execute_dag") and callable(operation.execute_dag):
        return operation.execute_dag(inputs, context)

    # Legacy-обёртка: один вход "in" → execute() → один выход "out"
    frame = inputs.get("in")
    result = operation.execute(frame, context)
    return {"out": result}
