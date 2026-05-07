"""apply_on_error_policy — единая обработка on_error для всех исполнителей.

Политика: skip / fail_region / fail_camera (любое значение, отличное от
"skip" и "fail_region", трактуется как fail_camera). Возвращает флаг
should_break — нужно ли прервать дальнейшее исполнение цепочки.
"""
from __future__ import annotations

from typing import Any

from .context import ChainContext
from .result import ChainResult, RunnableStep


def apply_on_error_policy(
    step: RunnableStep,
    exc: Exception,
    context: ChainContext,
    result: ChainResult,
    node_id: str | None = None,
) -> bool:
    """Обработать исключение шага согласно его on_error политике.

    Args:
        step: Шаг, на котором произошла ошибка.
        exc: Само исключение.
        context: Контекст выполнения (warnings/errors/logger).
        result: Результат цепочки (skipped_nodes/failed/fail_level).
        node_id: ID ноды; если None — берётся из step.node.node_id
                 (для DAG может отличаться при виртуальных нодах).

    Returns:
        should_break: True для fail_region/fail_camera (прервать цепочку),
                      False для skip (продолжить).
    """
    nid = node_id if node_id is not None else step.node.node_id
    op_ref = step.node.operation_ref
    log = context.logger

    if step.on_error == "skip":
        msg = (
            f"Операция '{op_ref}' (node={nid}) упала: {exc}. "
            f"on_error=skip — пропускаем."
        )
        if log is not None:
            log.log_warning(msg)
        context.warnings.append(msg)
        result.skipped_nodes.append(nid)
        return False

    if step.on_error == "fail_region":
        msg = (
            f"Операция '{op_ref}' (node={nid}) упала: {exc}. "
            f"on_error=fail_region — прерываем (region)."
        )
        if log is not None:
            log.log_error(msg)
        context.errors.append(msg)
        result.failed = True
        result.fail_level = "region"
        return True

    msg = (
        f"Операция '{op_ref}' (node={nid}) упала: {exc}. "
        f"on_error={step.on_error} — прерываем (camera)."
    )
    if log is not None:
        log.log_error(msg)
    context.errors.append(msg)
    result.failed = True
    result.fail_level = "camera"
    return True


__all__ = ["apply_on_error_policy"]
