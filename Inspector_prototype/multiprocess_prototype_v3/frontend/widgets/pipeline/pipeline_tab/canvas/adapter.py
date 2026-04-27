"""NodeGraphQtAdapter — адаптер между NodeGraphQt и нашей бизнес-логикой.

NodeGraphQt отвечает за визуализацию графа (ноды, порты, рёбра, pan/zoom).
ВСЕ мутации графа идут через ActionBus -> handlers -> GraphEditorModel,
а adapter транслирует Qt-сигналы в Action-команды и обновляет NodeGraphQt
при изменении модели (undo/redo, load_pipeline, apply_layout).

Ключевые паттерны:
- _suppress_graph_signals / _block_signals() — предотвращение бесконечного цикла
  (programmatic update → signal → action → update → ...).
- Identity маппинг node_id (наш UUID) <-> InspectorBaseNode (NodeGraphQt) через _node_map.
- Type-validation при коннекте: несовместимые порты отменяются ДО создания edge.
- Coalescing для moved_nodes (не требуется — viewer emits один раз на drop).

# TODO(framework): кандидат на миграцию — паттерн «adapter между внешней
# Qt-библиотекой и model+bus с signal-suppression context manager».
# Универсален для любых Qt-компонентов, работающих поверх ActionBus.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Iterator

from PySide6 import QtCore

if TYPE_CHECKING:
    from NodeGraphQt import BaseNode, NodeGraph

    from frontend.actions.bus import ActionBus
    from frontend.widgets.pipeline.pipeline_tab.canvas.model import GraphEditorModel
    from frontend.widgets.pipeline.pipeline_tab.inspector.inspector_node import InspectorBaseNode
    from registers.processor.catalog.schemas import ProcessingOperationDef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Константа: тип ноды, регистрируемый в NodeGraphQt
# ---------------------------------------------------------------------------

# NodeGraphQt требует зарегистрировать тип ноды (строка) перед create_node.
# Все наши operation'ы используют единый базовый тип — InspectorNode.
INSPECTOR_NODE_TYPE = "inspector.nodes.InspectorNode"


class NodeGraphQtAdapter(QtCore.QObject):
    """Адаптер между NodeGraphQt (рендеринг) и нашей бизнес-логикой
    (GraphEditorModel + ActionBus + auto_layout + are_ports_compatible).

    NodeGraphQt отвечает только за визуализацию и user input.
    ВСЕ изменения графа идут через ActionBus -> handlers -> GraphEditorModel,
    а потом отражаются обратно в NodeGraphQt через _refresh_from_model().

    Наследуется от QObject чтобы поддерживать Qt-сигналы (node_selected,
    selection_cleared, connection_rejected) для Inspector panel (Task 9.10).

    # TODO(framework): кандидат на миграцию — паттерн signal-suppression
    # context manager для виджетов с двусторонней синхронизацией (model <-> view).
    """

    # --- Qt-сигналы для Inspector panel (Task 9.10) ---
    node_selected = QtCore.Signal(str)          # node_id при клике на ноду
    selection_cleared = QtCore.Signal()          # когда selection пуст
    connection_rejected = QtCore.Signal(str, str, str)  # source, target, reason

    def __init__(
        self,
        graph: NodeGraph,
        model: GraphEditorModel,
        action_bus: ActionBus,
        catalog: dict[str, ProcessingOperationDef],
        *,
        region_id: str = "default",
        parent: QtCore.QObject | None = None,
    ) -> None:
        """Инициализация адаптера.

        Args:
            graph: экземпляр NodeGraphQt.NodeGraph (уже созданный с QApplication).
            model: наша GraphEditorModel (хранит ProcessingNode'ы).
            action_bus: ActionBus (execute/undo/redo, handlers зарегистрированы).
            catalog: словарь type_key -> ProcessingOperationDef из каталога.
            region_id: ID региона — используется как register_name в Action'ах.
            parent: Qt-родитель для корректного lifecycle.
        """
        super().__init__(parent)

        self._graph = graph
        self._model = model
        self._action_bus = action_bus
        self._catalog = catalog
        self._region_id = region_id

        # Identity маппинг: наш node_id (UUID str) -> InspectorBaseNode (NodeGraphQt)
        # После Task 9.8 все ноды — InspectorBaseNode (subclass BaseNode).
        self._node_map: dict[str, InspectorBaseNode] = {}

        # Обратный маппинг: NodeGraphQt node.id -> наш node_id
        self._reverse_map: dict[str, str] = {}

        # Флаг подавления сигналов при programmatic update
        self._suppress_graph_signals: bool = False

        # Подключаем Qt-сигналы NodeGraphQt к нашим обработчикам
        self._connect_signals()

        # Подписываемся на изменения ActionBus для рефлективных обновлений
        self._action_bus.add_change_callback(self._on_action_bus_changed)

        logger.debug(
            "NodeGraphQtAdapter инициализирован: region_id=%s, catalog=%d операций",
            self._region_id,
            len(self._catalog),
        )

    # ------------------------------------------------------------------
    # Signal suppression — предотвращение бесконечного цикла
    # ------------------------------------------------------------------
    # TODO(framework): кандидат на миграцию в
    # multiprocess_framework/modules/frontend_module/widgets/signal_suppression.py
    # Паттерн «context manager для подавления сигналов при programmatic update»
    # универсален для любых виджетов с двусторонней синхронизацией.

    @contextmanager
    def _block_signals(self) -> Iterator[None]:
        """Контекстный менеджер: подавляет обработку Qt-сигналов NodeGraphQt.

        При programmatic update (load_pipeline, apply_layout, undo/redo)
        изменения в NodeGraphQt не должны триггерить ActionBus.
        """
        prev = self._suppress_graph_signals
        self._suppress_graph_signals = True
        try:
            yield
        finally:
            self._suppress_graph_signals = prev

    # ------------------------------------------------------------------
    # Подключение Qt-сигналов NodeGraphQt
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Подключить сигналы NodeGraphQt к нашим обработчикам."""
        self._graph.port_connected.connect(self._on_port_connected)
        self._graph.port_disconnected.connect(self._on_port_disconnected)
        self._graph.node_created.connect(self._on_node_created)
        self._graph.nodes_deleted.connect(self._on_nodes_deleted)
        self._graph.node_selection_changed.connect(
            self._on_node_selection_changed,
        )

        # moved_nodes — сигнал viewer'а, fires один раз на mouse release
        # (не на каждый mouseMoveEvent), поэтому QTimer-coalescing не нужен.
        # {node_view: previous_pos} — viewer-internal, обрабатываем через viewer.
        self._graph.viewer().moved_nodes.connect(self._on_nodes_moved_internal)

    def disconnect_signals(self) -> None:
        """Отключить все сигналы. Вызывать при dispose/удалении адаптера."""
        try:
            self._graph.port_connected.disconnect(self._on_port_connected)
            self._graph.port_disconnected.disconnect(self._on_port_disconnected)
            self._graph.node_created.disconnect(self._on_node_created)
            self._graph.nodes_deleted.disconnect(self._on_nodes_deleted)
            self._graph.node_selection_changed.disconnect(
                self._on_node_selection_changed,
            )
            self._graph.viewer().moved_nodes.disconnect(
                self._on_nodes_moved_internal,
            )
        except (RuntimeError, TypeError):
            # Объекты уже удалены — игнорируем
            pass

        self._action_bus.remove_change_callback(self._on_action_bus_changed)

    # ------------------------------------------------------------------
    # Загрузка pipeline -> NodeGraphQt сцена
    # ------------------------------------------------------------------

    def load_pipeline(self, nodes: dict[str, Any]) -> None:
        """Загрузить dict[node_id -> ProcessingNode] в NodeGraphQt сцену.

        Очищает текущую сцену и создаёт ноды + связи из модели.
        Programmatic — все сигналы подавлены.

        Args:
            nodes: словарь node_id -> ProcessingNode (Pydantic-объект).
        """
        with self._block_signals():
            self._clear_graph()

            # Фаза 1: создаём все ноды
            for node_id, proc_node in nodes.items():
                self._create_qt_node(node_id, proc_node)

            # Фаза 2: создаём связи (inputs каждой ноды)
            for node_id, proc_node in nodes.items():
                for inp in proc_node.inputs:
                    if inp.source == "frame":
                        continue  # виртуальный источник, не рисуем
                    self._create_qt_connection(
                        source_node_id=inp.source,
                        output_port=inp.output_port,
                        target_node_id=node_id,
                        input_port=inp.input_port,
                    )

        logger.debug(
            "load_pipeline: загружено %d нод в NodeGraphQt",
            len(nodes),
        )

    # ------------------------------------------------------------------
    # Применение auto-layout (Sugiyama координаты)
    # ------------------------------------------------------------------

    def apply_layout(
        self, positions: dict[str, tuple[float, float]],
    ) -> None:
        """Sugiyama-координаты -> BaseNode.set_pos().

        Programmatic — сигналы подавлены. Позиции также обновляются
        в модели через move_node (без ActionBus, т.к. layout — не user action).

        Args:
            positions: словарь node_id -> (x, y).
        """
        with self._block_signals():
            for node_id, (x, y) in positions.items():
                qt_node = self._node_map.get(node_id)
                if qt_node is not None:
                    qt_node.set_pos(x, y)

        logger.debug(
            "apply_layout: установлены позиции для %d нод",
            len(positions),
        )

    # ------------------------------------------------------------------
    # Qt-сигнал: port_connected(in_port, out_port)
    # ------------------------------------------------------------------

    def _on_port_connected(self, in_port: Any, out_port: Any) -> None:
        """Обработчик сигнала port_connected от NodeGraphQt.

        Порядок аргументов NodeGraphQt: (input_port, output_port).
        Наша конвенция: source (output) -> target (input).

        1. Проверяем type-compatibility через are_ports_compatible.
        2. Если несовместимо — отменяем соединение и эмитим connection_rejected.
        3. Если совместимо — создаём Action(GRAPH_CONNECT) и вызываем ActionBus.
        """
        if self._suppress_graph_signals:
            return

        from registers.processor.catalog.port_types import are_ports_compatible

        # NodeGraphQt: in_port = input port, out_port = output port
        target_qt_node = in_port.node()
        source_qt_node = out_port.node()

        target_node_id = self._reverse_map.get(target_qt_node.id)
        source_node_id = self._reverse_map.get(source_qt_node.id)

        if target_node_id is None or source_node_id is None:
            logger.warning(
                "_on_port_connected: нода не найдена в reverse_map "
                "(target=%s, source=%s)",
                target_qt_node.id,
                source_qt_node.id,
            )
            return

        # Получаем operation_ref -> определение -> порты -> data_type
        target_proc_node = self._model.nodes.get(target_node_id)
        source_proc_node = self._model.nodes.get(source_node_id)

        if target_proc_node is None or source_proc_node is None:
            logger.warning(
                "_on_port_connected: ProcessingNode не найден в модели "
                "(target=%s, source=%s)",
                target_node_id,
                source_node_id,
            )
            return

        target_op = self._catalog.get(target_proc_node.operation_ref)
        source_op = self._catalog.get(source_proc_node.operation_ref)

        if target_op is None or source_op is None:
            logger.warning(
                "_on_port_connected: операция не найдена в каталоге "
                "(target_op=%s, source_op=%s)",
                target_proc_node.operation_ref,
                source_proc_node.operation_ref,
            )
            return

        # Ищем data_type для output_port и input_port
        output_port_name = out_port.name()
        input_port_name = in_port.name()

        source_port_def = next(
            (p for p in source_op.output_ports if p.name == output_port_name),
            None,
        )
        target_port_def = next(
            (p for p in target_op.input_ports if p.name == input_port_name),
            None,
        )

        if source_port_def is None or target_port_def is None:
            logger.warning(
                "_on_port_connected: определение порта не найдено "
                "(output=%s, input=%s)",
                output_port_name,
                input_port_name,
            )
            return

        # --- Type-validation ---
        if not are_ports_compatible(
            source_port_def.data_type, target_port_def.data_type,
        ):
            reason = (
                f"Несовместимые типы: {source_port_def.data_type} "
                f"-> {target_port_def.data_type}"
            )
            logger.info(
                "Соединение отклонено: %s.%s -> %s.%s — %s",
                source_node_id,
                output_port_name,
                target_node_id,
                input_port_name,
                reason,
            )

            # Отменяем соединение в NodeGraphQt
            with self._block_signals():
                in_port.disconnect_from(out_port)

            self.connection_rejected.emit(
                source_node_id, target_node_id, reason,
            )
            return

        # --- Совместимо: создаём Action ---
        nodes_before = self._snapshot_nodes()

        try:
            self._model.connect(
                source_node_id, output_port_name,
                target_node_id, input_port_name,
            )
        except (KeyError, ValueError) as exc:
            logger.warning(
                "_on_port_connected: model.connect failed: %s", exc,
            )
            with self._block_signals():
                in_port.disconnect_from(out_port)
            self.connection_rejected.emit(
                source_node_id, target_node_id, str(exc),
            )
            return

        nodes_after = self._snapshot_nodes()

        from frontend.actions.builder import ActionBuilder

        action = ActionBuilder.graph_connect(
            region_id=self._region_id,
            source_node_id=source_node_id,
            output_port=output_port_name,
            target_node_id=target_node_id,
            input_port=input_port_name,
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        # record (не execute) — модель уже обновлена; нужно только положить в стек
        self._action_bus.record(action)

    # ------------------------------------------------------------------
    # Qt-сигнал: port_disconnected(in_port, out_port)
    # ------------------------------------------------------------------

    def _on_port_disconnected(self, in_port: Any, out_port: Any) -> None:
        """Обработчик сигнала port_disconnected от NodeGraphQt.

        Создаёт Action(GRAPH_DISCONNECT) и записывает в ActionBus.
        """
        if self._suppress_graph_signals:
            return

        target_qt_node = in_port.node()
        source_qt_node = out_port.node()

        target_node_id = self._reverse_map.get(target_qt_node.id)
        source_node_id = self._reverse_map.get(source_qt_node.id)

        if target_node_id is None or source_node_id is None:
            logger.warning(
                "_on_port_disconnected: нода не найдена в reverse_map",
            )
            return

        output_port_name = out_port.name()
        input_port_name = in_port.name()

        nodes_before = self._snapshot_nodes()

        try:
            self._model.disconnect(
                target_node_id, input_port_name, source_node_id,
            )
        except (KeyError, ValueError) as exc:
            logger.warning(
                "_on_port_disconnected: model.disconnect failed: %s", exc,
            )
            return

        nodes_after = self._snapshot_nodes()

        from frontend.actions.builder import ActionBuilder

        action = ActionBuilder.graph_disconnect(
            region_id=self._region_id,
            source_node_id=source_node_id,
            output_port=output_port_name,
            target_node_id=target_node_id,
            input_port=input_port_name,
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        self._action_bus.record(action)

    # ------------------------------------------------------------------
    # Qt-сигнал: node_created(node)
    # ------------------------------------------------------------------

    def _on_node_created(self, qt_node: Any) -> None:
        """Обработчик сигнала node_created от NodeGraphQt.

        NodeGraphQt уже создал BaseNode. Мы достаём operation_ref из node
        property и создаём ProcessingNode в модели через ActionBus.

        Примечание: при programmatic create (load_pipeline) сигнал подавлен.
        """
        if self._suppress_graph_signals:
            return

        # operation_ref хранится в custom property ноды
        op_ref = qt_node.get_property("operation_ref")
        if op_ref is None:
            logger.warning(
                "_on_node_created: нода %s не содержит operation_ref",
                qt_node.id,
            )
            return

        if op_ref not in self._catalog:
            logger.warning(
                "_on_node_created: operation_ref '%s' не найден в каталоге",
                op_ref,
            )
            return

        # Генерируем наш node_id
        from uuid import uuid4
        node_id = str(uuid4())

        pos = qt_node.pos()
        position = (pos[0], pos[1]) if pos else None

        nodes_before = self._snapshot_nodes()

        try:
            self._model.add_node(
                operation_ref=op_ref,
                position=position,
                node_id=node_id,
            )
        except KeyError as exc:
            logger.warning(
                "_on_node_created: model.add_node failed: %s", exc,
            )
            return

        # Регистрируем маппинг
        self._node_map[node_id] = qt_node
        self._reverse_map[qt_node.id] = node_id

        nodes_after = self._snapshot_nodes()

        from frontend.actions.builder import ActionBuilder

        action = ActionBuilder.graph_node_add(
            region_id=self._region_id,
            node_data={"node_id": node_id, "operation_ref": op_ref},
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        self._action_bus.record(action)

    # ------------------------------------------------------------------
    # Qt-сигнал: nodes_deleted(node_ids)
    # ------------------------------------------------------------------

    def _on_nodes_deleted(self, node_ids: list[str]) -> None:
        """Обработчик сигнала nodes_deleted от NodeGraphQt.

        node_ids — список NodeGraphQt internal IDs (не наших UUID).
        Для каждого находим наш node_id и удаляем из модели.
        """
        if self._suppress_graph_signals:
            return

        for qt_node_id in node_ids:
            our_node_id = self._reverse_map.get(qt_node_id)
            if our_node_id is None:
                logger.warning(
                    "_on_nodes_deleted: qt_node_id=%s не найден в reverse_map",
                    qt_node_id,
                )
                continue

            nodes_before = self._snapshot_nodes()

            try:
                self._model.remove_node(our_node_id)
            except KeyError as exc:
                logger.warning(
                    "_on_nodes_deleted: model.remove_node failed: %s", exc,
                )
                continue

            nodes_after = self._snapshot_nodes()

            from frontend.actions.builder import ActionBuilder

            action = ActionBuilder.graph_node_remove(
                region_id=self._region_id,
                node_id=our_node_id,
                nodes_before=nodes_before,
                nodes_after=nodes_after,
            )

            self._action_bus.record(action)

            # Очищаем маппинг
            self._node_map.pop(our_node_id, None)
            self._reverse_map.pop(qt_node_id, None)

    # ------------------------------------------------------------------
    # Viewer-сигнал: moved_nodes({node_view: prev_pos})
    # ------------------------------------------------------------------
    # NodeGraphQt viewer emits moved_nodes ОДИН РАЗ на mouseReleaseEvent
    # (не на каждый mouseMoveEvent). Поэтому QTimer-coalescing не нужен —
    # каждый emit = одна завершённая операция drag.

    def _on_nodes_moved_internal(self, node_data: dict) -> None:
        """Обработчик viewer.moved_nodes — fires на mouse release.

        Args:
            node_data: {NodeItem (view): QPointF (previous_pos)}.
        """
        if self._suppress_graph_signals:
            return

        from frontend.actions.builder import ActionBuilder

        for node_view, prev_pos in node_data.items():
            qt_node_id = node_view.id
            our_node_id = self._reverse_map.get(qt_node_id)
            if our_node_id is None:
                continue

            # prev_pos — QPointF предыдущей позиции (до drag)
            old_pos: tuple[float, float] = (prev_pos.x(), prev_pos.y())
            # Текущая позиция — из node_view
            new_pos: tuple[float, float] = (
                node_view.xy_pos[0],
                node_view.xy_pos[1],
            )

            if old_pos == new_pos:
                continue  # Не двигали — пропускаем

            # Обновляем модель напрямую (move_node не нуждается в ActionBus handler)
            try:
                self._model.move_node(our_node_id, new_pos[0], new_pos[1])
            except KeyError:
                continue

            action = ActionBuilder.graph_node_move(
                region_id=self._region_id,
                node_id=our_node_id,
                old_pos=old_pos,
                new_pos=new_pos,
            )

            self._action_bus.record(action)

    # ------------------------------------------------------------------
    # Qt-сигнал: node_selection_changed(selected_nodes, deselected_nodes)
    # ------------------------------------------------------------------

    def _on_node_selection_changed(
        self,
        selected: list[Any],
        deselected: list[Any],
    ) -> None:
        """Обработчик смены выделения нод.

        Эмитим node_selected / selection_cleared для Inspector panel.
        """
        if self._suppress_graph_signals:
            return

        if selected:
            # Берём первую выделенную ноду (Inspector показывает одну)
            qt_node = selected[0]
            our_node_id = self._reverse_map.get(qt_node.id)
            if our_node_id is not None:
                self.node_selected.emit(our_node_id)
        elif not selected and deselected:
            # Всё снято с выделения
            self.selection_cleared.emit()

    # ------------------------------------------------------------------
    # Рефлективные обновления: ActionBus -> NodeGraphQt
    # ------------------------------------------------------------------

    def _on_action_bus_changed(self) -> None:
        """Callback от ActionBus — вызывается после execute/undo/redo.

        Если последнее действие — undo/redo graph-операции, нужно
        обновить NodeGraphQt из модели.
        """
        event = self._action_bus.last_event
        if event is None:
            return

        event_type, action = event
        if event_type not in ("undo", "redo"):
            return  # execute уже обработан через сигналы

        from frontend.actions.schemas import ActionType

        graph_types = {
            ActionType.GRAPH_CONNECT,
            ActionType.GRAPH_DISCONNECT,
            ActionType.GRAPH_NODE_ADD,
            ActionType.GRAPH_NODE_REMOVE,
            ActionType.GRAPH_NODE_MOVE,
        }

        if action.action_type not in graph_types:
            return

        # При undo/redo graph-операций: полный refresh из модели
        if action.action_type == ActionType.GRAPH_NODE_MOVE:
            # Для move — точечное обновление позиции
            self._refresh_node_position(action, event_type)
        else:
            # Для остальных — полный refresh
            self._refresh_from_model()

    def _refresh_node_position(self, action: Any, event_type: str) -> None:
        """Обновить позицию ноды в NodeGraphQt при undo/redo GRAPH_NODE_MOVE."""
        if event_type == "undo":
            patch = action.backward_patch
            pos = patch.get("old_pos")
        else:
            patch = action.forward_patch
            pos = patch.get("new_pos")

        node_id = patch.get("node_id")
        if node_id is None or pos is None:
            return

        qt_node = self._node_map.get(node_id)
        if qt_node is not None:
            with self._block_signals():
                qt_node.set_pos(pos[0], pos[1])

    def _refresh_from_model(self) -> None:
        """Полное обновление NodeGraphQt сцены из текущего состояния модели.

        Используется при undo/redo операций add/remove/connect/disconnect.
        Стратегия: очистить и загрузить заново (простое и надёжное).
        """
        current_nodes = self._model.nodes
        self.load_pipeline(current_nodes)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _clear_graph(self) -> None:
        """Удалить все ноды из NodeGraphQt сцены (без сигналов)."""
        for qt_node in list(self._node_map.values()):
            try:
                self._graph.delete_node(qt_node, push_undo=False)
            except Exception:
                pass  # Нода уже удалена — игнорируем
        self._node_map.clear()
        self._reverse_map.clear()

    def _create_qt_node(
        self, node_id: str, proc_node: Any,
    ) -> BaseNode | None:
        """Создать BaseNode в NodeGraphQt из ProcessingNode.

        Args:
            node_id: наш UUID.
            proc_node: ProcessingNode (Pydantic).

        Returns:
            Созданный BaseNode или None при ошибке.
        """
        op_def = self._catalog.get(proc_node.operation_ref)
        if op_def is None:
            logger.warning(
                "_create_qt_node: операция '%s' не найдена в каталоге",
                proc_node.operation_ref,
            )
            return None

        try:
            qt_node = self._graph.create_node(
                INSPECTOR_NODE_TYPE,
                name=op_def.name,
                selected=False,
                push_undo=False,
            )
        except Exception as exc:
            logger.error(
                "_create_qt_node: ошибка создания ноды: %s", exc,
            )
            return None

        # Сохраняем operation_ref в custom property
        qt_node.create_property("operation_ref", proc_node.operation_ref)
        qt_node.create_property("our_node_id", node_id)

        # Позиция
        if proc_node.position is not None:
            qt_node.set_pos(*proc_node.position)

        # Создаём порты из определения операции
        self._setup_ports(qt_node, op_def)

        # Устанавливаем display_capable из каталога (Task 9.8)
        if hasattr(qt_node, "set_display_capable") and hasattr(op_def, "display_capable"):
            qt_node.set_display_capable(op_def.display_capable)

        # Регистрируем маппинг
        self._node_map[node_id] = qt_node
        self._reverse_map[qt_node.id] = node_id

        return qt_node

    def _setup_ports(self, qt_node: BaseNode, op_def: Any) -> None:
        """Настроить входные/выходные порты на BaseNode из ProcessingOperationDef.

        Args:
            qt_node: нода NodeGraphQt.
            op_def: ProcessingOperationDef с input_ports и output_ports.
        """
        for port_def in op_def.input_ports:
            qt_node.add_input(
                name=port_def.name,
                multi_input=False,
            )

        for port_def in op_def.output_ports:
            qt_node.add_output(
                name=port_def.name,
                multi_output=True,
            )

    def _create_qt_connection(
        self,
        source_node_id: str,
        output_port: str,
        target_node_id: str,
        input_port: str,
    ) -> bool:
        """Создать визуальное соединение (edge) в NodeGraphQt.

        Args:
            source_node_id: наш node_id источника.
            output_port: имя выходного порта.
            target_node_id: наш node_id приёмника.
            input_port: имя входного порта.

        Returns:
            True если соединение создано, False при ошибке.
        """
        source_qt = self._node_map.get(source_node_id)
        target_qt = self._node_map.get(target_node_id)

        if source_qt is None or target_qt is None:
            logger.warning(
                "_create_qt_connection: нода не найдена "
                "(source=%s, target=%s)",
                source_node_id,
                target_node_id,
            )
            return False

        out_port = source_qt.get_output(output_port)
        in_port = target_qt.get_input(input_port)

        if out_port is None or in_port is None:
            logger.warning(
                "_create_qt_connection: порт не найден "
                "(output=%s, input=%s)",
                output_port,
                input_port,
            )
            return False

        try:
            out_port.connect_to(in_port, push_undo=False)
        except Exception as exc:
            logger.warning(
                "_create_qt_connection: ошибка создания edge: %s", exc,
            )
            return False

        return True

    def _snapshot_nodes(self) -> dict[str, Any]:
        """Снимок текущего состояния nodes из модели (deepcopy).

        Используется для forward_patch/backward_patch в Action'ах.
        """
        return deepcopy(self._model.nodes)

    # ------------------------------------------------------------------
    # Public API — добавление ноды через адаптер (для palette, drag-drop)
    # ------------------------------------------------------------------

    def add_node_from_catalog(
        self,
        operation_ref: str,
        position: tuple[float, float] | None = None,
    ) -> str | None:
        """Добавить ноду из каталога — единая точка входа для UI.

        Создаёт ProcessingNode в модели + BaseNode в NodeGraphQt + Action.

        Args:
            operation_ref: type_key операции из каталога.
            position: (x, y) позиция на сцене.

        Returns:
            node_id созданной ноды или None при ошибке.
        """
        op_def = self._catalog.get(operation_ref)
        if op_def is None:
            logger.warning(
                "add_node_from_catalog: операция '%s' не найдена",
                operation_ref,
            )
            return None

        from uuid import uuid4
        node_id = str(uuid4())

        nodes_before = self._snapshot_nodes()

        try:
            self._model.add_node(
                operation_ref=operation_ref,
                position=position,
                node_id=node_id,
            )
        except KeyError as exc:
            logger.warning(
                "add_node_from_catalog: model.add_node failed: %s", exc,
            )
            return None

        # Создаём ноду в NodeGraphQt (без сигналов)
        proc_node = self._model.nodes.get(node_id)
        if proc_node is None:
            return None

        with self._block_signals():
            qt_node = self._create_qt_node(node_id, proc_node)

        if qt_node is None:
            # Откатываем модель
            try:
                self._model.remove_node(node_id)
            except KeyError:
                pass
            return None

        nodes_after = self._snapshot_nodes()

        from frontend.actions.builder import ActionBuilder

        action = ActionBuilder.graph_node_add(
            region_id=self._region_id,
            node_data={"node_id": node_id, "operation_ref": operation_ref},
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        self._action_bus.record(action)
        return node_id

    # ------------------------------------------------------------------
    # Свойства (read-only)
    # ------------------------------------------------------------------

    @property
    def node_map(self) -> dict[str, Any]:
        """Копия маппинга node_id -> BaseNode (для тестов/отладки)."""
        return dict(self._node_map)

    @property
    def reverse_map(self) -> dict[str, str]:
        """Копия обратного маппинга qt_node_id -> our_node_id."""
        return dict(self._reverse_map)

    @property
    def graph(self) -> NodeGraph:
        """Ссылка на NodeGraphQt граф."""
        return self._graph

    @property
    def model(self) -> GraphEditorModel:
        """Ссылка на GraphEditorModel."""
        return self._model

    @property
    def region_id(self) -> str:
        """ID региона, используемый как register_name."""
        return self._region_id


__all__ = ["NodeGraphQtAdapter", "INSPECTOR_NODE_TYPE"]
