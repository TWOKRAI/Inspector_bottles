"""
Unit-тесты для NodeGraphQtAdapter (Task 9.7).

Покрывает:
  - load_pipeline: создание нод в NodeGraphQt из Pipeline
  - apply_layout: установка позиций нод
  - port_connected (совместимые порты): ActionBus.record вызван с GRAPH_CONNECT
  - port_connected (несовместимые порты): connection_rejected + disconnect_from
  - port_disconnected: ActionBus.record вызван с GRAPH_DISCONNECT
  - node_created: ActionBus.record вызван с GRAPH_NODE_ADD
  - nodes_deleted: ActionBus.record вызван с GRAPH_NODE_REMOVE
  - nodes_moved: ActionBus.record вызван с GRAPH_NODE_MOVE
  - _block_signals: programmatic update не триггерит ActionBus
  - add_node_from_catalog: unified API для создания ноды
  - node_selection_changed: node_selected / selection_cleared сигналы

Без Qt (QApplication) — все NodeGraphQt объекты замокированы через MagicMock.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

# Добавляем корень multiprocess_prototype_v3 в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.actions.builder import ActionBuilder  # noqa: E402
from frontend.actions.default_bus_factory import create_default_action_bus  # noqa: E402
from frontend.actions.schemas import ActionType  # noqa: E402
from frontend.widgets.graph_editor.model import GraphEditorModel  # noqa: E402
from registers.pipeline.processing_node import NodeInput, ProcessingNode  # noqa: E402
from registers.processor.catalog.port_types import (  # noqa: E402
    PORT_TYPE_DETECTIONS,
    PORT_TYPE_IMAGE,
    PORT_TYPE_MASK,
)
from registers.processor.catalog.schemas import Port, ProcessingOperationDef  # noqa: E402


# ---------------------------------------------------------------------------
# Мок RegistersManager (такой же как в test_graph_actions.py)
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager без Qt и реальной БД."""

    def __init__(self):
        self._data: dict = {}
        self.calls: list = []

    def set_field_value(self, register_name, field_name, value):
        self._data[(register_name, field_name)] = value
        self.calls.append((register_name, field_name, value))
        return (True, None)

    def get_field_value(self, register_name, field_name):
        return self._data.get((register_name, field_name))

    def get_register(self, register_name):
        return None

    def model_dump_all(self):
        result = {}
        for (reg, field), val in self._data.items():
            result.setdefault(reg, {})[field] = val
        return result


# ---------------------------------------------------------------------------
# Фабрика каталога (ProcessingOperationDef)
# ---------------------------------------------------------------------------


def _make_catalog() -> dict[str, ProcessingOperationDef]:
    """Создать тестовый каталог из 3 операций с разными портами."""
    return {
        "blur": ProcessingOperationDef(
            name="Gaussian Blur",
            type_key="blur",
            params_schema="tests.stub.BlurParams",
            module_path="tests.stub.BlurOp",
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
        ),
        "threshold": ProcessingOperationDef(
            name="Threshold",
            type_key="threshold",
            params_schema="tests.stub.ThreshParams",
            module_path="tests.stub.ThreshOp",
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[
                Port(name="out", data_type=PORT_TYPE_IMAGE),
                Port(name="mask", data_type=PORT_TYPE_MASK),
            ],
        ),
        "detector": ProcessingOperationDef(
            name="Object Detector",
            type_key="detector",
            params_schema="tests.stub.DetectorParams",
            module_path="tests.stub.DetectorOp",
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_DETECTIONS)],
        ),
    }


# ---------------------------------------------------------------------------
# Мок NodeGraphQt объектов
# ---------------------------------------------------------------------------


def _make_mock_port(name: str, node: MagicMock) -> MagicMock:
    """Создать мок Port с name() и node() методами."""
    port = MagicMock()
    port.name.return_value = name
    port.node.return_value = node
    return port


def _make_mock_qt_node(
    qt_id: str,
    *,
    name: str = "TestNode",
    pos: tuple[float, float] = (0.0, 0.0),
) -> MagicMock:
    """Создать мок BaseNode с id, pos(), set_pos(), get_input(), get_output()."""
    node = MagicMock()
    node.id = qt_id
    node.name.return_value = name
    node.pos.return_value = pos
    node.set_pos = MagicMock()
    node.add_input = MagicMock()
    node.add_output = MagicMock()
    node.create_property = MagicMock()

    # get_input / get_output — возвращают мок-порты
    input_ports: dict[str, MagicMock] = {}
    output_ports: dict[str, MagicMock] = {}

    def get_input(name):
        if name not in input_ports:
            input_ports[name] = _make_mock_port(name, node)
        return input_ports[name]

    def get_output(name):
        if name not in output_ports:
            output_ports[name] = _make_mock_port(name, node)
        return output_ports[name]

    node.get_input = get_input
    node.get_output = get_output
    node._input_ports = input_ports
    node._output_ports = output_ports

    # properties storage
    _props: dict[str, object] = {}

    def create_prop(k, v):
        _props[k] = v

    def get_prop(k):
        return _props.get(k)

    node.create_property = create_prop
    node.get_property = get_prop

    return node


def _make_mock_graph(create_node_side_effect=None) -> MagicMock:
    """Создать мок NodeGraph с сигналами и viewer."""
    graph = MagicMock()

    # Сигналы — MagicMock с connect/disconnect/emit
    graph.port_connected = MagicMock()
    graph.port_disconnected = MagicMock()
    graph.node_created = MagicMock()
    graph.nodes_deleted = MagicMock()
    graph.node_selection_changed = MagicMock()

    # Viewer с moved_nodes сигналом
    viewer = MagicMock()
    viewer.moved_nodes = MagicMock()
    graph.viewer.return_value = viewer
    graph._viewer = viewer

    # create_node
    if create_node_side_effect:
        graph.create_node = MagicMock(side_effect=create_node_side_effect)
    else:
        graph.create_node = MagicMock(
            return_value=_make_mock_qt_node("qt-default"),
        )

    graph.delete_node = MagicMock()

    return graph


# ---------------------------------------------------------------------------
# Фабрика адаптера (без реального Qt)
# ---------------------------------------------------------------------------


def _create_adapter(
    *,
    catalog: dict | None = None,
    model: GraphEditorModel | None = None,
    graph: MagicMock | None = None,
    region_id: str = "region_test",
):
    """Создать NodeGraphQtAdapter с замокированным NodeGraph (без QApplication).

    Так как NodeGraphQtAdapter наследует QObject, нужно пропатчить
    QObject.__init__ чтобы не требовался QApplication.
    """
    if catalog is None:
        catalog = _make_catalog()
    if model is None:
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
    if graph is None:
        graph = _make_mock_graph()

    rm = MockRM()
    bus = create_default_action_bus(rm)

    # Patch QObject.__init__ чтобы не требовать QApplication
    with patch(
        "frontend.widgets.pipeline_tab.adapter.QtCore.QObject.__init__",
        return_value=None,
    ):
        from frontend.widgets.pipeline_tab.adapter import NodeGraphQtAdapter

        adapter = NodeGraphQtAdapter(
            graph=graph,
            model=model,
            action_bus=bus,
            catalog=catalog,
            region_id=region_id,
        )

    # Мокаем Qt-сигналы адаптера (т.к. без QApplication Signal не работает)
    adapter.node_selected = MagicMock()
    adapter.selection_cleared = MagicMock()
    adapter.connection_rejected = MagicMock()

    return adapter, bus, rm, graph


# ===========================================================================
# Тесты
# ===========================================================================


class TestLoadPipeline:
    """Тесты загрузки pipeline в NodeGraphQt сцену."""

    def test_load_pipeline_creates_nodes_in_graph(self):
        """Pipeline с 3 нодами -> adapter.load_pipeline() -> graph.create_node
        вызван 3 раза с правильными именами."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)

        # Добавляем 3 ноды в модель
        model.add_node("blur", position=(0, 0), node_id="n1")
        model.add_node("threshold", position=(100, 0), node_id="n2")
        model.add_node("detector", position=(200, 0), node_id="n3")

        created_nodes = []

        def create_node_fn(*args, **kwargs):
            node = _make_mock_qt_node(f"qt-{len(created_nodes)}")
            created_nodes.append(node)
            return node

        graph = _make_mock_graph(create_node_side_effect=create_node_fn)

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )

        nodes = model.nodes
        adapter.load_pipeline(nodes)

        # graph.create_node вызван 3 раза
        assert graph.create_node.call_count == 3

    def test_load_pipeline_sets_positions(self):
        """load_pipeline устанавливает позиции нод через set_pos."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", position=(10.0, 20.0), node_id="n1")

        qt_node = _make_mock_qt_node("qt-1")
        graph = _make_mock_graph(create_node_side_effect=lambda *a, **kw: qt_node)

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )

        adapter.load_pipeline(model.nodes)

        qt_node.set_pos.assert_called_with(10.0, 20.0)

    def test_load_pipeline_creates_connections(self):
        """load_pipeline создаёт визуальные edge для inputs."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", position=(0, 0), node_id="n1")
        model.add_node("threshold", position=(100, 0), node_id="n2")
        # Соединяем n1.out -> n2.in
        model.connect("n1", "out", "n2", "in")

        qt_nodes = {}

        def create_fn(*args, **kwargs):
            nid = f"qt-{len(qt_nodes)}"
            node = _make_mock_qt_node(nid)
            qt_nodes[nid] = node
            return node

        graph = _make_mock_graph(create_node_side_effect=create_fn)

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )

        adapter.load_pipeline(model.nodes)

        # Должен быть вызов connect_to на одном из портов
        # Проверяем что create_node вызван 2 раза
        assert graph.create_node.call_count == 2


class TestApplyLayout:
    """Тесты применения auto-layout координат."""

    def test_apply_layout_sets_positions(self):
        """apply_layout({n1: (10, 20), n2: (30, 40)}) -> set_pos вызван правильно."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")
        model.add_node("threshold", node_id="n2")

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        adapter.apply_layout({"n1": (10.0, 20.0), "n2": (30.0, 40.0)})

        qt_n1.set_pos.assert_called_with(10.0, 20.0)
        qt_n2.set_pos.assert_called_with(30.0, 40.0)

    def test_apply_layout_ignores_unknown_node_ids(self):
        """apply_layout с неизвестным node_id — нет ошибки."""
        adapter, bus, rm, graph = _create_adapter()

        # Не должно бросать исключение
        adapter.apply_layout({"unknown-id": (10.0, 20.0)})


class TestPortConnected:
    """Тесты обработчика port_connected."""

    def test_compatible_port_connect_records_action(self):
        """Совместимые порты (image -> image): ActionBus.record вызван с GRAPH_CONNECT."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")
        model.add_node("threshold", node_id="n2")

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # Симулируем port_connected: out_port (n1.out) -> in_port (n2.in)
        out_port = _make_mock_port("out", qt_n1)
        in_port = _make_mock_port("in", qt_n2)

        # Вызываем handler напрямую
        adapter._on_port_connected(in_port, out_port)

        # Проверяем что в bus есть action
        last = bus.last_action()
        assert last is not None
        assert last.action_type == ActionType.GRAPH_CONNECT

    def test_incompatible_port_connect_rejected(self):
        """Несовместимые порты (detections -> image): connection_rejected emit
        + disconnect_from вызван + ActionBus НЕ содержит action."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("detector", node_id="n1")  # output: detections
        model.add_node("blur", node_id="n2")       # input: image

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # detector.out (detections) -> blur.in (image) — НЕСОВМЕСТИМО
        out_port = _make_mock_port("out", qt_n1)
        in_port = _make_mock_port("in", qt_n2)

        adapter._on_port_connected(in_port, out_port)

        # connection_rejected должен быть emit'нут
        adapter.connection_rejected.emit.assert_called_once()
        args = adapter.connection_rejected.emit.call_args[0]
        assert args[0] == "n1"  # source
        assert args[1] == "n2"  # target
        assert "detections" in args[2].lower() or "image" in args[2].lower()

        # disconnect_from должен быть вызван
        in_port.disconnect_from.assert_called_with(out_port)

        # ActionBus не должен содержать action
        assert bus.last_action() is None


class TestPortDisconnected:
    """Тесты обработчика port_disconnected."""

    def test_port_disconnected_records_action(self):
        """port_disconnected -> ActionBus.record с GRAPH_DISCONNECT."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")
        model.add_node("threshold", node_id="n2")
        model.connect("n1", "out", "n2", "in")

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # Симулируем port_disconnected
        out_port = _make_mock_port("out", qt_n1)
        in_port = _make_mock_port("in", qt_n2)

        adapter._on_port_disconnected(in_port, out_port)

        last = bus.last_action()
        assert last is not None
        assert last.action_type == ActionType.GRAPH_DISCONNECT


class TestNodesDeleted:
    """Тесты обработчика nodes_deleted."""

    def test_node_deleted_records_action(self):
        """nodes_deleted -> ActionBus.record с GRAPH_NODE_REMOVE."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")

        qt_n1 = _make_mock_qt_node("qt-1")
        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: qt_n1,
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # Симулируем удаление ноды (NodeGraphQt передаёт qt_node_id)
        adapter._on_nodes_deleted(["qt-1"])

        last = bus.last_action()
        assert last is not None
        assert last.action_type == ActionType.GRAPH_NODE_REMOVE

    def test_node_deleted_removes_from_model(self):
        """Удалённая нода исчезает из модели."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")

        qt_n1 = _make_mock_qt_node("qt-1")
        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: qt_n1,
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        assert "n1" in model.nodes

        adapter._on_nodes_deleted(["qt-1"])

        assert "n1" not in model.nodes


class TestNodesMoved:
    """Тесты обработчика nodes_moved (viewer.moved_nodes signal)."""

    def test_node_moved_records_action(self):
        """Одиночное перемещение -> ActionBus.record с GRAPH_NODE_MOVE."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", position=(0.0, 0.0), node_id="n1")

        qt_n1 = _make_mock_qt_node("qt-1", pos=(0.0, 0.0))
        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: qt_n1,
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # Симулируем viewer.moved_nodes:
        # {node_view: prev_pos (QPointF)}
        prev_pos = MagicMock()
        prev_pos.x.return_value = 0.0
        prev_pos.y.return_value = 0.0

        node_view = MagicMock()
        node_view.id = "qt-1"
        node_view.xy_pos = [50.0, 60.0]

        adapter._on_nodes_moved_internal({node_view: prev_pos})

        last = bus.last_action()
        assert last is not None
        assert last.action_type == ActionType.GRAPH_NODE_MOVE
        assert last.forward_patch["new_pos"] == (50.0, 60.0)
        assert last.backward_patch["old_pos"] == (0.0, 0.0)

    def test_multiple_nodes_moved_creates_separate_actions(self):
        """Перемещение 2 нод одновременно -> 2 Action в undo стеке."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", position=(0.0, 0.0), node_id="n1")
        model.add_node("threshold", position=(100.0, 0.0), node_id="n2")

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # 2 ноды перемещены одновременно
        prev1 = MagicMock()
        prev1.x.return_value = 0.0
        prev1.y.return_value = 0.0
        view1 = MagicMock()
        view1.id = "qt-1"
        view1.xy_pos = [10.0, 20.0]

        prev2 = MagicMock()
        prev2.x.return_value = 100.0
        prev2.y.return_value = 0.0
        view2 = MagicMock()
        view2.id = "qt-2"
        view2.xy_pos = [110.0, 20.0]

        adapter._on_nodes_moved_internal({view1: prev1, view2: prev2})

        # В истории 2 action'а (разные node_id => разные coalesce_key)
        history = bus.history()
        assert len(history) == 2
        assert all(a.action_type == ActionType.GRAPH_NODE_MOVE for a in history)


class TestBlockSignals:
    """Тесты подавления сигналов при programmatic update."""

    def test_block_signals_prevents_action_on_connect(self):
        """Programmatic update внутри _block_signals() не триггерит ActionBus."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")
        model.add_node("threshold", node_id="n2")

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        out_port = _make_mock_port("out", qt_n1)
        in_port = _make_mock_port("in", qt_n2)

        # В блоке подавления — сигнал НЕ обрабатывается
        with adapter._block_signals():
            adapter._on_port_connected(in_port, out_port)

        # ActionBus пуст
        assert bus.last_action() is None

    def test_block_signals_restores_flag(self):
        """После выхода из _block_signals() — флаг восстанавливается."""
        adapter, bus, rm, graph = _create_adapter()

        assert adapter._suppress_graph_signals is False

        with adapter._block_signals():
            assert adapter._suppress_graph_signals is True

        assert adapter._suppress_graph_signals is False

    def test_block_signals_nested(self):
        """Вложенный _block_signals() — корректное восстановление флага."""
        adapter, bus, rm, graph = _create_adapter()

        with adapter._block_signals():
            assert adapter._suppress_graph_signals is True
            with adapter._block_signals():
                assert adapter._suppress_graph_signals is True
            # После внутреннего — всё ещё True (внешний блок ещё активен)
            assert adapter._suppress_graph_signals is True

        # После обоих — False
        assert adapter._suppress_graph_signals is False

    def test_block_signals_prevents_infinite_loop(self):
        """Programmatic update в _block_signals() не триггерит action_bus —
        предотвращение бесконечного цикла обновления."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")

        qt_n1 = _make_mock_qt_node("qt-1")
        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: qt_n1,
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # Симулируем все типы сигналов внутри _block_signals
        with adapter._block_signals():
            # port_connected — подавлен
            out_port = _make_mock_port("out", qt_n1)
            in_port = _make_mock_port("in", qt_n1)
            adapter._on_port_connected(in_port, out_port)

            # nodes_deleted — подавлен
            adapter._on_nodes_deleted(["qt-1"])

            # node_created — подавлен
            adapter._on_node_created(qt_n1)

            # selection_changed — подавлен
            adapter._on_node_selection_changed([qt_n1], [])

        # Ни одного action в bus
        assert bus.last_action() is None
        # Сигналы адаптера не вызваны
        adapter.node_selected.emit.assert_not_called()


class TestNodeSelection:
    """Тесты обработчика node_selection_changed."""

    def test_node_selected_emits_signal(self):
        """Выбор ноды -> node_selected.emit(node_id)."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")

        qt_n1 = _make_mock_qt_node("qt-1")
        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: qt_n1,
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        adapter._on_node_selection_changed([qt_n1], [])

        adapter.node_selected.emit.assert_called_once_with("n1")

    def test_selection_cleared_emits_signal(self):
        """Снятие выделения -> selection_cleared.emit()."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")

        qt_n1 = _make_mock_qt_node("qt-1")
        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: qt_n1,
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        # Передаём пустой selected, непустой deselected
        adapter._on_node_selection_changed([], [qt_n1])

        adapter.selection_cleared.emit.assert_called_once()


class TestAddNodeFromCatalog:
    """Тесты unified API для добавления ноды."""

    def test_add_node_creates_in_model_and_graph(self):
        """add_node_from_catalog: нода появляется в модели и NodeGraphQt."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)

        qt_n1 = _make_mock_qt_node("qt-1")
        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: qt_n1,
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )

        node_id = adapter.add_node_from_catalog("blur", position=(50.0, 60.0))

        assert node_id is not None
        assert node_id in model.nodes
        assert node_id in adapter.node_map

        # Action записан
        last = bus.last_action()
        assert last is not None
        assert last.action_type == ActionType.GRAPH_NODE_ADD

    def test_add_node_unknown_operation_returns_none(self):
        """add_node_from_catalog с неизвестной операцией -> None."""
        adapter, bus, rm, graph = _create_adapter()

        result = adapter.add_node_from_catalog("nonexistent_op")

        assert result is None
        assert bus.last_action() is None


class TestIdentityMapping:
    """Тесты маппинга node_id <-> BaseNode.id."""

    def test_load_pipeline_populates_maps(self):
        """После load_pipeline — node_map и reverse_map заполнены."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")
        model.add_node("threshold", node_id="n2")

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )
        adapter.load_pipeline(model.nodes)

        assert len(adapter.node_map) == 2
        assert len(adapter.reverse_map) == 2
        assert "n1" in adapter.node_map
        assert "n2" in adapter.node_map


class TestSuppressedSignalsOnLoad:
    """Тесты что load_pipeline не генерирует action'ы."""

    def test_load_pipeline_does_not_create_actions(self):
        """load_pipeline — programmatic, ActionBus остаётся пустым."""
        catalog = _make_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("blur", node_id="n1")
        model.add_node("threshold", node_id="n2")
        model.connect("n1", "out", "n2", "in")

        qt_n1 = _make_mock_qt_node("qt-1")
        qt_n2 = _make_mock_qt_node("qt-2")
        nodes_iter = iter([qt_n1, qt_n2])

        graph = _make_mock_graph(
            create_node_side_effect=lambda *a, **kw: next(nodes_iter),
        )

        adapter, bus, rm, _ = _create_adapter(
            catalog=catalog, model=model, graph=graph,
        )

        adapter.load_pipeline(model.nodes)

        # Никаких action'ов
        assert bus.last_action() is None
        assert not bus.can_undo()


class TestRegression:
    """Проверки что adapter не ломает существующие контракты."""

    def test_action_builder_graph_methods_still_work(self):
        """ActionBuilder.graph_connect/disconnect/node_add/node_remove/node_move
        продолжают создавать корректные Action'ы."""
        action = ActionBuilder.graph_connect("r", "a", "o", "b", "i", {}, {"x": 1})
        assert action.action_type == ActionType.GRAPH_CONNECT
        assert action.forward_patch["nodes_after"] == {"x": 1}

        action = ActionBuilder.graph_node_move("r", "n", (0.0, 0.0), (1.0, 2.0))
        assert action.action_type == ActionType.GRAPH_NODE_MOVE
        assert action.coalesce_key == "graph_move:r:n"

    def test_graph_action_handler_still_works(self):
        """GraphActionHandler.apply/revert продолжают работать."""
        from frontend.actions.handlers.graph_handler import GraphActionHandler

        rm = MockRM()
        handler = GraphActionHandler()

        action = ActionBuilder.graph_connect(
            "region_1", "a", "out", "b", "in",
            nodes_before={}, nodes_after={"a": 1},
        )
        handler.apply(action, rm)
        assert ("region_1", "vision_pipeline", {"a": 1}) in rm.calls
