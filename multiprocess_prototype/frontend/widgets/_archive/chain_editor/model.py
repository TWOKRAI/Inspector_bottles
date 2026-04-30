"""Модель состояния Chain Editor."""

from __future__ import annotations

from uuid import uuid4

from registers.pipeline.processing_node import ProcessingNode
from registers.processor.catalog.schemas import ProcessingOperationDef


class ChainEditorModel:
    """Хранит текущее состояние цепочки узлов и каталог операций.

    nodes — упорядоченный dict: node_id → ProcessingNode.
    Порядок dict определяет порядок выполнения цепочки.
    """

    def __init__(self) -> None:
        """Инициализация с пустым состоянием."""
        # Текущие ноды региона (node_id → ProcessingNode, порядок важен)
        self.nodes: dict[str, ProcessingNode] = {}
        # Каталог доступных операций (type_key → ProcessingOperationDef)
        self.catalog: dict[str, ProcessingOperationDef] = {}
        # ID текущего региона
        self.region_id: str = ""
        # Количество доступных воркеров (определяет варианты в dropdown Worker)
        self.worker_count: int = 2

    # --- Публичный API ---

    def add_node(self, operation_ref: str) -> str:
        """Добавить новый узел с указанной операцией в конец цепочки.

        Возвращает node_id созданного узла.
        """
        node_id = str(uuid4())
        node = ProcessingNode(operation_ref=operation_ref, node_id=node_id)
        self.nodes[node_id] = node
        return node_id

    def remove_node(self, node_id: str) -> None:
        """Удалить узел по node_id. Если узел не найден — ничего не делает."""
        self.nodes.pop(node_id, None)

    def move_up(self, node_id: str) -> None:
        """Переместить узел на одну позицию вверх (ближе к началу цепочки)."""
        ordered = list(self.nodes.items())
        idx = self._find_index(ordered, node_id)
        if idx is None or idx == 0:
            return
        # Меняем местами с предыдущим элементом
        ordered[idx], ordered[idx - 1] = ordered[idx - 1], ordered[idx]
        self.nodes = dict(ordered)

    def move_down(self, node_id: str) -> None:
        """Переместить узел на одну позицию вниз (ближе к концу цепочки)."""
        ordered = list(self.nodes.items())
        idx = self._find_index(ordered, node_id)
        if idx is None or idx >= len(ordered) - 1:
            return
        # Меняем местами со следующим элементом
        ordered[idx], ordered[idx + 1] = ordered[idx + 1], ordered[idx]
        self.nodes = dict(ordered)

    def toggle_enabled(self, node_id: str) -> None:
        """Инвертировать флаг enabled у узла."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        self.nodes[node_id] = node.model_copy(update={"enabled": not node.enabled})

    def get_ordered_nodes(self) -> list[tuple[str, ProcessingNode]]:
        """Вернуть узлы в порядке выполнения цепочки.

        Возвращает список пар (node_id, ProcessingNode).
        """
        return list(self.nodes.items())

    # --- Вспомогательные методы ---

    @staticmethod
    def _find_index(
        ordered: list[tuple[str, ProcessingNode]],
        node_id: str,
    ) -> int | None:
        """Найти индекс узла в упорядоченном списке по node_id."""
        for i, (nid, _) in enumerate(ordered):
            if nid == node_id:
                return i
        return None
