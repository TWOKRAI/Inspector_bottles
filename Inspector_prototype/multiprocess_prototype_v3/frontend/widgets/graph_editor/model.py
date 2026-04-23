"""GraphEditorModel — модель данных графового редактора (без UI).

Хранит ProcessingNode'ы и каталог операций, предоставляет методы мутации.
Каждая мутация возвращает (old_state, new_state) для будущего undo.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4


class GraphEditorModel:
    """Модель данных графа обработки.

    Работает с dict-представлениями ProcessingNode (Dict at Boundary).
    Валидирует ацикличность и совместимость портов при создании связей.
    """

    def __init__(self) -> None:
        # node_id → ProcessingNode (Pydantic-объект)
        self._nodes: dict[str, Any] = {}
        # type_key → ProcessingOperationDef (Pydantic-объект)
        self._catalog: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def load(
        self,
        nodes: dict[str, Any],
        catalog: dict[str, Any],
    ) -> None:
        """Загрузить данные графа.

        Args:
            nodes: словарь node_id → ProcessingNode.
            catalog: словарь type_key → ProcessingOperationDef.
        """
        self._nodes = dict(nodes)
        self._catalog = dict(catalog)

    @property
    def nodes(self) -> dict[str, Any]:
        return dict(self._nodes)

    @property
    def catalog(self) -> dict[str, Any]:
        return dict(self._catalog)

    # ------------------------------------------------------------------
    # Мутации (возвращают (old_state, new_state) для undo)
    # ------------------------------------------------------------------

    def add_node(
        self,
        operation_ref: str,
        position: tuple[float, float] | None = None,
        params: dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> tuple[None, Any]:
        """Добавить новый узел в граф.

        Args:
            operation_ref: type_key операции из каталога.
            position: (x, y) позиция на сцене.
            params: параметры операции.
            node_id: UUID (если None — генерируется автоматически).

        Returns:
            (None, созданный ProcessingNode) — old_state = None (узла не было).

        Raises:
            KeyError: если operation_ref не найден в каталоге.
        """
        if operation_ref not in self._catalog:
            raise KeyError(f"Операция '{operation_ref}' не найдена в каталоге")

        # Ленивый импорт, чтобы не тянуть зависимости при простом импорте model.py
        from registers.pipeline.processing_node import ProcessingNode

        nid = node_id or str(uuid4())
        node = ProcessingNode(
            node_id=nid,
            operation_ref=operation_ref,
            params=params or {},
            position=position,
        )
        self._nodes[nid] = node
        return (None, deepcopy(node))

    def remove_node(self, node_id: str) -> tuple[Any, None]:
        """Удалить узел и все его входящие/исходящие связи.

        Returns:
            (удалённый ProcessingNode, None).

        Raises:
            KeyError: если узел не найден.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Узел '{node_id}' не найден")

        old_node = deepcopy(self._nodes.pop(node_id))

        # Удаляем все входы, ссылающиеся на удалённый узел
        for node in self._nodes.values():
            node.inputs = [inp for inp in node.inputs if inp.source != node_id]

        return (old_node, None)

    def connect(
        self,
        source_node_id: str,
        output_port: str,
        target_node_id: str,
        input_port: str,
    ) -> tuple[Any, Any]:
        """Создать связь между выходным портом source и входным портом target.

        Проверяет:
        1. Существование нод и портов.
        2. Совместимость типов данных.
        3. Ацикличность графа после добавления связи.

        Returns:
            (old_inputs_copy, new_inputs_copy) — для undo.

        Raises:
            KeyError: нода или порт не найдены.
            ValueError: несовместимые типы или цикл.
        """
        # Проверка существования нод
        if source_node_id not in self._nodes:
            raise KeyError(f"Исходный узел '{source_node_id}' не найден")
        if target_node_id not in self._nodes:
            raise KeyError(f"Целевой узел '{target_node_id}' не найден")

        source_node = self._nodes[source_node_id]
        target_node = self._nodes[target_node_id]

        # Проверка существования портов
        source_op = self._catalog.get(source_node.operation_ref)
        target_op = self._catalog.get(target_node.operation_ref)
        if source_op is None or target_op is None:
            raise KeyError("Операция не найдена в каталоге")

        source_port_def = next((p for p in source_op.output_ports if p.name == output_port), None)
        target_port_def = next((p for p in target_op.input_ports if p.name == input_port), None)
        if source_port_def is None:
            raise KeyError(f"Выходной порт '{output_port}' не найден")
        if target_port_def is None:
            raise KeyError(f"Входной порт '{input_port}' не найден")

        # Совместимость типов
        from registers.processor.catalog.port_types import are_ports_compatible

        if not are_ports_compatible(source_port_def.data_type, target_port_def.data_type):
            raise ValueError(
                f"Несовместимые типы: {source_port_def.data_type} → {target_port_def.data_type}"
            )

        # Проверка на дубликат
        from registers.pipeline.processing_node import NodeInput

        for inp in target_node.inputs:
            if inp.input_port == input_port and inp.source == source_node_id:
                raise ValueError("Такое соединение уже существует")

        # Сохраняем old state
        old_inputs = deepcopy(target_node.inputs)

        # Проверка ацикличности
        new_input = NodeInput(
            source=source_node_id,
            output_port=output_port,
            input_port=input_port,
        )
        target_node.inputs.append(new_input)

        if self._has_cycle():
            # Откатываем
            target_node.inputs.pop()
            raise ValueError("Добавление связи создаёт цикл в графе")

        new_inputs = deepcopy(target_node.inputs)
        return (old_inputs, new_inputs)

    def disconnect(
        self,
        target_node_id: str,
        input_port: str,
        source_node_id: str | None = None,
    ) -> tuple[Any, Any]:
        """Удалить связь (вход) из target-ноды.

        Args:
            target_node_id: ID целевой ноды.
            input_port: имя входного порта.
            source_node_id: (опц.) ID исходной ноды — для точного удаления.

        Returns:
            (old_inputs, new_inputs) — для undo.
        """
        if target_node_id not in self._nodes:
            raise KeyError(f"Узел '{target_node_id}' не найден")

        target_node = self._nodes[target_node_id]
        old_inputs = deepcopy(target_node.inputs)

        if source_node_id:
            target_node.inputs = [
                inp
                for inp in target_node.inputs
                if not (inp.input_port == input_port and inp.source == source_node_id)
            ]
        else:
            target_node.inputs = [inp for inp in target_node.inputs if inp.input_port != input_port]

        new_inputs = deepcopy(target_node.inputs)
        return (old_inputs, new_inputs)

    def move_node(
        self,
        node_id: str,
        x: float,
        y: float,
    ) -> tuple[tuple[float, float] | None, tuple[float, float]]:
        """Обновить позицию узла.

        Returns:
            (old_position, new_position).
        """
        if node_id not in self._nodes:
            raise KeyError(f"Узел '{node_id}' не найден")

        node = self._nodes[node_id]
        old_pos = node.position
        node.position = (x, y)
        return (old_pos, (x, y))

    # ------------------------------------------------------------------
    # Валидация: проверка на циклы (DFS)
    # ------------------------------------------------------------------

    def _has_cycle(self) -> bool:
        """Проверяет наличие цикла в графе (DFS)."""
        # Строим граф смежности: target → [sources]
        adjacency: dict[str, list[str]] = {nid: [] for nid in self._nodes}
        for nid, node in self._nodes.items():
            for inp in node.inputs:
                if inp.source in adjacency:
                    adjacency[inp.source].append(nid)

        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            in_stack.add(node_id)

            for neighbor in adjacency.get(node_id, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in in_stack:
                    return True

            in_stack.discard(node_id)
            return False

        return any(nid not in visited and dfs(nid) for nid in self._nodes)
