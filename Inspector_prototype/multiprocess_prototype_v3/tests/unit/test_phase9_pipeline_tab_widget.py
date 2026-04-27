"""Unit-тесты для PipelineTabWidget (Task 9.13).

Покрывает:
  - Создание виджета: все 3 секции (palette / view_switch / inspector) присутствуют.
  - set_pipeline: model.nodes обновляется, current_pipeline возвращает снимок.
  - node_selected -> Inspector показывает ноду.
  - selection_cleared -> Inspector очищается.
  - palette присутствует и содержит загруженные операции.
  - drop_target зарегистрирован на viewport (MIME принимается).
  - model property доступен снаружи.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from PySide6 import QtCore, QtWidgets  # noqa: E402

from frontend.actions.default_bus_factory import create_default_action_bus  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.library.library_palette import MIME_TYPE  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.canvas.model import GraphEditorModel  # noqa: E402


# ---------------------------------------------------------------------------
# Мок RegistersManager (минимальный, для create_default_action_bus)
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager без Qt и реальной БД."""

    def __init__(self):
        self._data: dict = {}

    def set_field_value(self, register_name, field_name, value):
        self._data[(register_name, field_name)] = value
        return (True, None)

    def get_field_value(self, register_name, field_name):
        return self._data.get((register_name, field_name))

    def get_register(self, register_name):
        return None
from registers.pipeline.processing_node import NodeInput, ProcessingNode  # noqa: E402
from registers.processor.catalog.port_types import (  # noqa: E402
    PORT_TYPE_IMAGE,
    PORT_TYPE_MASK,
)
from registers.processor.catalog.schemas import Port, ProcessingOperationDef  # noqa: E402


# ---------------------------------------------------------------------------
# QApplication fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


# ---------------------------------------------------------------------------
# Каталог с 2 операциями
# ---------------------------------------------------------------------------


def _make_catalog() -> dict[str, ProcessingOperationDef]:
    """Каталог из 2 операций: blur (image->image) и threshold (image->image+mask)."""
    return {
        "blur": ProcessingOperationDef(
            name="Gaussian Blur",
            type_key="blur",
            params_schema="tests.stub.BlurParams",
            module_path="tests.stub.BlurOp",
            category="Preprocess",
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
        ),
        "threshold": ProcessingOperationDef(
            name="Threshold",
            type_key="threshold",
            params_schema="tests.stub.ThreshParams",
            module_path="tests.stub.ThreshOp",
            category="Detect",
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[
                Port(name="out", data_type=PORT_TYPE_IMAGE),
                Port(name="mask", data_type=PORT_TYPE_MASK),
            ],
        ),
    }


# ---------------------------------------------------------------------------
# Мок NodeGraph + InspectorBaseNode
# Реальный NodeGraph требует полную инициализацию Qt + OpenGL.
# Мы мокаем NodeGraph и InspectorBaseNode чтобы тесты оставались быстрыми.
# ---------------------------------------------------------------------------


def _make_mock_qt_node(qt_id: str, *, name: str = "TestNode") -> MagicMock:
    """Создать мок BaseNode."""
    node = MagicMock()
    node.id = qt_id
    node.name.return_value = name
    node.pos.return_value = (0.0, 0.0)
    node.set_pos = MagicMock()
    node.add_input = MagicMock()
    node.add_output = MagicMock()
    node.set_selected = MagicMock()

    _props: dict[str, object] = {}

    def create_prop(k, v):
        _props[k] = v

    def get_prop(k):
        return _props.get(k)

    node.create_property = create_prop
    node.get_property = get_prop

    input_ports: dict[str, MagicMock] = {}
    output_ports: dict[str, MagicMock] = {}

    def get_input(n):
        if n not in input_ports:
            p = MagicMock()
            p.name.return_value = n
            p.node.return_value = node
            input_ports[n] = p
        return input_ports[n]

    def get_output(n):
        if n not in output_ports:
            p = MagicMock()
            p.name.return_value = n
            p.node.return_value = node
            output_ports[n] = p
        return output_ports[n]

    node.get_input = get_input
    node.get_output = get_output

    return node


def _make_mock_graph() -> MagicMock:
    """Создать мок NodeGraph с viewer, widget, register_node, create_node."""
    graph = MagicMock()

    viewer = MagicMock()
    # viewport для drop target
    viewport = MagicMock(spec=QtWidgets.QWidget)
    viewport.installEventFilter = MagicMock()
    viewer.viewport.return_value = viewport
    viewer.mapToScene = MagicMock(return_value=QtCore.QPointF(100, 100))
    graph.viewer.return_value = viewer

    # widget — property, возвращает реальный QWidget (PySide6 strict)
    _real_widget = QtWidgets.QWidget()
    type(graph).widget = property(lambda self: _real_widget)
    graph._real_widget = _real_widget  # сохраняем ссылку чтобы не собрался GC

    # Сигналы NodeGraphQt
    graph.port_connected = MagicMock()
    graph.port_connected.connect = MagicMock()
    graph.port_disconnected = MagicMock()
    graph.port_disconnected.connect = MagicMock()
    graph.node_created = MagicMock()
    graph.node_created.connect = MagicMock()
    graph.nodes_deleted = MagicMock()
    graph.nodes_deleted.connect = MagicMock()
    graph.node_selection_changed = MagicMock()
    graph.node_selection_changed.connect = MagicMock()
    viewer.moved_nodes = MagicMock()
    viewer.moved_nodes.connect = MagicMock()

    # create_node — возвращает мок ноды
    _node_counter = {"i": 0}

    def create_node_fn(node_type, name="", selected=False, push_undo=True):
        _node_counter["i"] += 1
        return _make_mock_qt_node(f"qt_node_{_node_counter['i']}", name=name)

    graph.create_node = MagicMock(side_effect=create_node_fn)
    graph.register_node = MagicMock()
    graph.delete_node = MagicMock()

    return graph


# ---------------------------------------------------------------------------
# Fixture: PipelineTabWidget (с моком NodeGraph)
# ---------------------------------------------------------------------------


@pytest.fixture()
def pipeline_tab(qapp: QtWidgets.QApplication):
    """Создать PipelineTabWidget с моком NodeGraph и InspectorBaseNode."""
    catalog = _make_catalog()
    rm = MockRM()
    bus = create_default_action_bus(rm)

    mock_graph = _make_mock_graph()
    mock_inspector_node_cls = MagicMock()

    with (
        patch("NodeGraphQt.NodeGraph", return_value=mock_graph),
        patch(
            "frontend.widgets.pipeline.pipeline_tab.inspector.inspector_node.InspectorBaseNode",
            mock_inspector_node_cls,
        ),
    ):
        from frontend.widgets.pipeline.pipeline_tab.widget import PipelineTabWidget

        tab = PipelineTabWidget(
            action_bus=bus,
            catalog=catalog,
            region_id="test_region",
            known_processes_provider=lambda: ["proc_a", "proc_b"],
            known_displays_provider=lambda: ["disp_1"],
        )

    tab._test_graph = mock_graph
    tab._test_bus = bus
    tab._test_catalog = catalog

    yield tab
    tab.close()


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestPipelineTabWidgetCreation:
    """Проверка что виджет корректно собран из 3 секций."""

    def test_palette_is_child(self, pipeline_tab):
        """LibraryPalette присутствует как дочерний виджет."""
        from frontend.widgets.pipeline.pipeline_tab.library.library_palette import LibraryPalette

        children = pipeline_tab.findChildren(LibraryPalette)
        assert len(children) == 1, f"Ожидалась 1 LibraryPalette, найдено {len(children)}"

    def test_view_switch_is_child(self, pipeline_tab):
        """PipelineViewSwitch присутствует как дочерний виджет."""
        from frontend.widgets.pipeline.pipeline_tab.views.view_switch import PipelineViewSwitch

        children = pipeline_tab.findChildren(PipelineViewSwitch)
        assert len(children) == 1, f"Ожидался 1 PipelineViewSwitch, найдено {len(children)}"

    def test_inspector_is_child(self, pipeline_tab):
        """InspectorPanel присутствует как дочерний виджет."""
        from frontend.widgets.pipeline.pipeline_tab.inspector.inspector_panel import InspectorPanel

        children = pipeline_tab.findChildren(InspectorPanel)
        assert len(children) == 1, f"Ожидался 1 InspectorPanel, найдено {len(children)}"

    def test_model_property(self, pipeline_tab):
        """model property возвращает GraphEditorModel."""
        assert isinstance(pipeline_tab.model, GraphEditorModel)

    def test_initial_pipeline_empty(self, pipeline_tab):
        """Начальное состояние: pipeline пуст."""
        nodes = pipeline_tab.current_pipeline()
        assert nodes == {}


class TestSetPipeline:
    """Проверка set_pipeline / current_pipeline."""

    def test_set_pipeline_updates_model(self, pipeline_tab):
        """set_pipeline загружает ноды в model."""
        node = ProcessingNode(
            node_id="n1",
            operation_ref="blur",
            params={},
            position=(10, 20),
        )
        pipeline_tab.set_pipeline({"n1": node})

        model_nodes = pipeline_tab.model.nodes
        assert "n1" in model_nodes
        assert model_nodes["n1"].operation_ref == "blur"

    def test_current_pipeline_returns_snapshot(self, pipeline_tab):
        """current_pipeline возвращает deepcopy (изменение не влияет на модель)."""
        node = ProcessingNode(
            node_id="n1",
            operation_ref="blur",
            params={},
            position=(10, 20),
        )
        pipeline_tab.set_pipeline({"n1": node})

        snap = pipeline_tab.current_pipeline()
        assert "n1" in snap

        # Мутация снимка не должна влиять на модель
        snap.pop("n1")
        assert "n1" in pipeline_tab.current_pipeline()

    def test_set_pipeline_clears_inspector(self, pipeline_tab):
        """set_pipeline сбрасывает Inspector (clear)."""
        node = ProcessingNode(
            node_id="n1",
            operation_ref="blur",
            params={},
        )
        # Сначала покажем ноду
        pipeline_tab.set_pipeline({"n1": node})
        pipeline_tab._inspector.show_node_by_id("n1")
        assert pipeline_tab._inspector.current_node_id == "n1"

        # set_pipeline должен очистить inspector
        pipeline_tab.set_pipeline({})
        assert pipeline_tab._inspector.current_node_id is None

    def test_set_pipeline_calls_adapter_load(self, pipeline_tab):
        """set_pipeline вызывает adapter.load_pipeline."""
        node = ProcessingNode(
            node_id="n1",
            operation_ref="blur",
            params={},
        )
        # adapter.load_pipeline вызывается через set_pipeline
        with patch.object(pipeline_tab._adapter, "load_pipeline") as mock_load:
            pipeline_tab.set_pipeline({"n1": node})
            mock_load.assert_called_once()


class TestNodeSelection:
    """Проверка связки adapter.node_selected -> Inspector."""

    def test_node_selected_shows_in_inspector(self, pipeline_tab):
        """При adapter.node_selected('n1') Inspector показывает ноду."""
        node = ProcessingNode(
            node_id="n1",
            operation_ref="blur",
            params={},
        )
        pipeline_tab.set_pipeline({"n1": node})

        # Эмитим сигнал node_selected
        pipeline_tab._adapter.node_selected.emit("n1")

        assert pipeline_tab._inspector.current_node_id == "n1"

    def test_selection_cleared_clears_inspector(self, pipeline_tab):
        """При adapter.selection_cleared Inspector очищается."""
        node = ProcessingNode(
            node_id="n1",
            operation_ref="blur",
            params={},
        )
        pipeline_tab.set_pipeline({"n1": node})
        pipeline_tab._adapter.node_selected.emit("n1")
        assert pipeline_tab._inspector.current_node_id == "n1"

        pipeline_tab._adapter.selection_cleared.emit()
        assert pipeline_tab._inspector.current_node_id is None


class TestPaletteCatalog:
    """Проверка что палитра загружена каталогом."""

    def test_palette_has_categories(self, pipeline_tab):
        """Палитра содержит категории из каталога."""
        categories = pipeline_tab._palette.categories
        # blur = Preprocess, threshold = Detect
        assert "Preprocess" in categories
        assert "Detect" in categories

    def test_palette_fixed_width(self, pipeline_tab):
        """Палитра имеет фиксированную ширину 220."""
        assert pipeline_tab._palette.maximumWidth() == 220


class TestDropTarget:
    """Проверка что drop_target зарегистрирован."""

    def test_drop_target_exists(self, pipeline_tab):
        """LibraryDropTarget создан и сохранён."""
        assert pipeline_tab._drop_target is not None

    def test_drop_target_accepts_correct_mime(self, pipeline_tab):
        """Drop target должен принимать MIME_TYPE."""
        from frontend.widgets.pipeline.pipeline_tab.library.library_palette import LibraryDropTarget

        assert isinstance(pipeline_tab._drop_target, LibraryDropTarget)
        # Проверяем что drop target установлен как event filter на viewport
        # (install_palette_drop_target устанавливает eventFilter)
        graph = pipeline_tab._test_graph
        viewport = graph.viewer().viewport()
        viewport.installEventFilter.assert_called()


class TestInspectorWidth:
    """Проверка Inspector panel."""

    def test_inspector_fixed_width(self, pipeline_tab):
        """InspectorPanel имеет фиксированную ширину 320."""
        assert pipeline_tab._inspector.maximumWidth() == 320
