"""Базовые интерфейсы цепочки обработки кадров."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np

# ChainContext перемещён во фреймворк (Phase 2.3, ADR-CHN-002)
from multiprocess_framework.modules.chain_module import ChainContext

__all__ = ["ChainContext", "ProcessingOperation", "should_emit_preview", "execute_dag_default"]


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


def should_emit_preview(
    context: ChainContext,
    display_capable: bool = False,
    display_router: object | None = None,
    node_id: str = "",
) -> bool:
    """Проверить, нужно ли encode'ить preview-кадр для node thumbnail.

    Вызывается операцией перед дорогим encode (numpy → JPEG/SHM).
    Возвращает False если:
    - display_capable=False (операция не умеет публиковать preview).
    - Нет подписчиков на канал ``node_preview.{node_id}`` (viewport culling).

    Оптимизация на стороне publisher: экономим CPU + сериализацию
    когда ни один UI-клиент не заинтересован в кадре.

    Args:
        context: Текущий контекст цепочки обработки.
        display_capable: Из ProcessingOperationDef.display_capable.
        display_router: DisplayRouter (или None если недоступен).
        node_id: UUID ноды в графе.

    Returns:
        True если следует encode'ить и отправлять preview-кадр.
    """
    if not display_capable:
        return False

    if display_router is None:
        return False

    # Проверяем наличие подписчиков через DisplayRouter API
    channel = f"node_preview.{node_id}"
    if hasattr(display_router, "is_anyone_subscribed"):
        return display_router.is_anyone_subscribed(channel)

    return False


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
