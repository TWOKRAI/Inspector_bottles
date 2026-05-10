"""Автозаполнение inputs для линейной цепочки узлов (Phase 5a)."""

from __future__ import annotations

from registers.pipeline.processing_node import NodeInput, ProcessingNode


def autofill_inputs(nodes: dict[str, ProcessingNode]) -> dict[str, ProcessingNode]:
    """Заполняет inputs каждого узла по принципу линейной цепочки.

    Первый узел — inputs пустой (источник кадров не указывается явно).
    Каждый следующий узел берёт вход от предыдущего по node_id.

    Не мутирует входной dict — возвращает новый.
    """
    if not nodes:
        return {}

    result: dict[str, ProcessingNode] = {}
    prev_node_id: str | None = None

    for node_id, node in nodes.items():
        if prev_node_id is None:
            # Первый узел — входов нет
            updated = node.model_copy(update={"inputs": []})
        else:
            # Следующий узел — берёт выход предыдущего
            updated = node.model_copy(update={"inputs": [NodeInput(source=prev_node_id)]})

        result[node_id] = updated
        prev_node_id = node_id

    return result
