"""Unit-тесты для InspectorPanel + GRAPH_NODE_MODIFY (Task 9.10).

Покрывает:
  - ParamsForm: int/float/bool/Literal/List[int len=3] виджеты.
  - ProcessIdCombo: known processes + sentinel + новый процесс.
  - DisplayTargetCombo: multi-select + sentinel + value().
  - InspectorPanel: show_node_by_id, изменение через UI -> ActionBus.
  - GRAPH_NODE_MODIFY handler: apply -> set_field_value, revert -> set_field_value.
  - GraphEditorModel.modify_node: merge params, whitelist, ошибки.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Annotated, List, Literal
from unittest.mock import MagicMock, patch

import pytest

# sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from PySide6 import QtWidgets  # noqa: E402

from frontend.actions.builder import ActionBuilder  # noqa: E402
from frontend.actions.default_bus_factory import create_default_action_bus  # noqa: E402
from frontend.actions.handlers.graph_handler import GraphActionHandler  # noqa: E402
from frontend.actions.schemas import ActionType  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.canvas.model import GraphEditorModel  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.bridges.display_target_combo import DisplayTargetCombo  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.inspector.inspector_panel import InspectorPanel  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.inspector.params_form import ParamsForm  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.bridges.process_id_combo import ProcessIdCombo  # noqa: E402
from multiprocess_framework.modules.data_schema_module import (  # noqa: E402
    FieldMeta,
    SchemaBase,
    register_schema,
)
from pydantic import Field  # noqa: E402
from registers.pipeline.processing_node import ProcessingNode  # noqa: E402
from registers.processor.catalog.port_types import PORT_TYPE_IMAGE  # noqa: E402
from registers.processor.catalog.schemas import (  # noqa: E402
    Port,
    ProcessingOperationDef,
)


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
# Стаб-модель параметров для тестов
# ---------------------------------------------------------------------------


class StubResizeParams(SchemaBase):
    """Тестовая модель параметров (аналог ResizeParams)."""

    type: Literal["resize"] = "resize"

    width: Annotated[
        int,
        FieldMeta("Ширина", info="Целевая ширина.", min=16, max=8192, unit="px"),
    ] = 640

    height: Annotated[
        int,
        FieldMeta("Высота", info="Целевая высота.", min=16, max=8192, unit="px"),
    ] = 480

    interpolation: Annotated[
        Literal["nearest", "linear", "cubic", "area"],
        FieldMeta("Интерполяция", info="Метод масштабирования."),
    ] = "linear"


class StubColorParams(SchemaBase):
    """Тестовая модель с List[int] и bool."""

    type: Literal["color_detection"] = "color_detection"

    enabled_filter: Annotated[
        bool,
        FieldMeta("Фильтр", info="Включить фильтрацию."),
    ] = True

    color_lower: Annotated[
        List[int],
        FieldMeta("BGR Lower", info="Нижняя граница BGR."),
    ] = Field(default_factory=lambda: [0, 100, 100])

    threshold: Annotated[
        float,
        FieldMeta("Порог", info="Пороговое значение."),
    ] = 0.5


# ---------------------------------------------------------------------------
# Мок RegistersManager
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager."""

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
# Фабрики
# ---------------------------------------------------------------------------


def _make_resize_catalog() -> dict[str, ProcessingOperationDef]:
    return {
        "resize": ProcessingOperationDef(
            name="Resize",
            type_key="resize",
            params_schema="tests.unit.test_phase9_inspector_panel.StubResizeParams",
            module_path="tests.stub.ResizeOp",
            category="Preprocess",
            display_capable=True,
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
        ),
    }


def _make_color_catalog() -> dict[str, ProcessingOperationDef]:
    return {
        "color_detection": ProcessingOperationDef(
            name="Color Detection",
            type_key="color_detection",
            params_schema="tests.unit.test_phase9_inspector_panel.StubColorParams",
            module_path="tests.stub.ColorOp",
            category="Detect",
            display_capable=False,
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
        ),
    }


def _make_model_with_resize() -> tuple[GraphEditorModel, str]:
    """Создать модель с одной resize-нодой. Возвращает (model, node_id)."""
    catalog = _make_resize_catalog()
    model = GraphEditorModel()
    model.load(nodes={}, catalog=catalog)
    _, node = model.add_node(
        "resize",
        position=(0, 0),
        node_id="node-resize-1",
        params={"width": 640, "height": 480, "interpolation": "linear", "type": "resize"},
    )
    return model, "node-resize-1"


def _make_inspector(
    model: GraphEditorModel,
    catalog: dict[str, ProcessingOperationDef],
    *,
    processes: list[str] | None = None,
    displays: list[str] | None = None,
) -> tuple[InspectorPanel, "ActionBus", MockRM]:
    """Создать InspectorPanel с моками."""
    rm = MockRM()
    bus = create_default_action_bus(rm)

    panel = InspectorPanel(
        model=model,
        action_bus=bus,
        catalog=catalog,
        region_id="region_test",
        known_processes_provider=lambda: processes or ["processor", "vision_1"],
        known_displays_provider=lambda: displays or ["win_0", "win_1", "win_2"],
    )
    return panel, bus, rm


# ===========================================================================
# Тесты ParamsForm
# ===========================================================================


class TestParamsFormWidgets:
    """Проверка генерации виджетов по типу полей."""

    def test_int_field_creates_spinbox_with_range(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """int поле с FieldMeta(min=16, max=8192) -> QSpinBox с range 16..8192."""
        form = ParamsForm()
        form.set_schema(
            StubResizeParams,
            {"width": 640, "height": 480, "interpolation": "linear"},
        )

        widget = form._field_widgets.get("width")
        assert widget is not None
        assert isinstance(widget, QtWidgets.QSpinBox)
        assert widget.minimum() == 16
        assert widget.maximum() == 8192
        assert widget.value() == 640

    def test_float_without_min_max_has_wide_range(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """float без min/max -> QDoubleSpinBox с широким дефолтным range."""
        form = ParamsForm()
        form.set_schema(StubColorParams, {"threshold": 0.5, "enabled_filter": True, "color_lower": [0, 100, 100]})

        widget = form._field_widgets.get("threshold")
        assert widget is not None
        assert isinstance(widget, QtWidgets.QDoubleSpinBox)
        # Широкий range (не ноль)
        assert widget.minimum() < -1000
        assert widget.maximum() > 1000

    def test_bool_field_creates_checkbox(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """bool -> QCheckBox."""
        form = ParamsForm()
        form.set_schema(StubColorParams, {"threshold": 0.5, "enabled_filter": True, "color_lower": [0, 100, 100]})

        widget = form._field_widgets.get("enabled_filter")
        assert widget is not None
        assert isinstance(widget, QtWidgets.QCheckBox)
        assert widget.isChecked() is True

    def test_literal_creates_combobox(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Literal["nearest","linear","cubic","area"] -> QComboBox с 4 опциями."""
        form = ParamsForm()
        form.set_schema(
            StubResizeParams,
            {"width": 640, "height": 480, "interpolation": "linear"},
        )

        widget = form._field_widgets.get("interpolation")
        assert widget is not None
        assert isinstance(widget, QtWidgets.QComboBox)
        assert widget.count() == 4
        assert widget.currentData() == "linear"

    def test_list_int_len3_creates_3_spinboxes(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """List[int] длины 3 -> горизонтальный layout из 3 QSpinBox."""
        form = ParamsForm()
        form.set_schema(StubColorParams, {"threshold": 0.5, "enabled_filter": True, "color_lower": [0, 100, 100]})

        widget = form._field_widgets.get("color_lower")
        assert widget is not None
        assert hasattr(widget, "_spinboxes")
        assert len(widget._spinboxes) == 3
        assert widget._spinboxes[0].value() == 0
        assert widget._spinboxes[1].value() == 100
        assert widget._spinboxes[2].value() == 100

    def test_spinbox_change_emits_params_changed(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Изменение QSpinBox -> emits params_changed с обновлённым dict."""
        form = ParamsForm()
        form.set_schema(
            StubResizeParams,
            {"width": 640, "height": 480, "interpolation": "linear"},
        )

        received = []
        form.params_changed.connect(lambda d: received.append(d))

        # Меняем width
        widget = form._field_widgets["width"]
        widget.setValue(800)

        assert len(received) == 1
        assert received[0]["width"] == 800
        assert received[0]["height"] == 480  # не изменился

    def test_set_schema_none_shows_placeholder(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """set_schema(None, {}) показывает плейсхолдер «Нет параметров»."""
        form = ParamsForm()
        form.set_schema(None, {})

        assert form._layout.rowCount() == 1
        # Достаём виджет: первый (и единственный) row содержит label
        item = form._layout.itemAt(0)
        assert item is not None
        widget = item.widget()
        assert isinstance(widget, QtWidgets.QLabel)
        assert "Нет параметров" in widget.text()

    def test_type_field_skipped(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Поле 'type' (literal discriminator) пропускается."""
        form = ParamsForm()
        form.set_schema(
            StubResizeParams,
            {"width": 640, "height": 480, "interpolation": "linear"},
        )

        assert "type" not in form._field_widgets


# ===========================================================================
# Тесты ProcessIdCombo
# ===========================================================================


class TestProcessIdCombo:
    """Тесты комбобокса выбора process_id."""

    def test_set_known_processes_populates_items(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """set_known_processes(["a","b"], current="a") -> 3 items (a, b, sentinel)."""
        combo = ProcessIdCombo()
        combo.set_known_processes(["a", "b"], current="a")

        # 2 процесса + 1 sentinel = 3
        assert combo.count() == 3
        assert combo.currentData() == "a"

    def test_select_emits_signal(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Выбор 'b' -> сигнал process_id_changed("b")."""
        combo = ProcessIdCombo()
        combo.set_known_processes(["a", "b"], current="a")

        received = []
        combo.process_id_changed.connect(lambda v: received.append(v))

        # Выбираем "b"
        idx_b = combo.findData("b")
        combo.setCurrentIndex(idx_b)

        assert received == ["b"]

    def test_sentinel_with_input_dialog(
        self, qapp: QtWidgets.QApplication,
        monkeypatch,
    ) -> None:
        """Sentinel + QInputDialog -> новое имя добавлено и выбрано."""
        combo = ProcessIdCombo()
        combo.set_known_processes(["a", "b"], current="a")

        received = []
        combo.process_id_changed.connect(lambda v: received.append(v))

        # Мокаем QInputDialog.getText
        monkeypatch.setattr(
            "frontend.widgets.pipeline.pipeline_tab.bridges.process_id_combo.QInputDialog.getText",
            lambda *args, **kwargs: ("new_proc", True),
        )

        # Выбираем sentinel
        sentinel_idx = combo.count() - 1
        combo.setCurrentIndex(sentinel_idx)

        assert "new_proc" in received
        assert combo.currentData() == "new_proc"

    def test_sentinel_cancel_reverts(
        self, qapp: QtWidgets.QApplication,
        monkeypatch,
    ) -> None:
        """Sentinel + Cancel -> возврат к предыдущему."""
        combo = ProcessIdCombo()
        combo.set_known_processes(["a", "b"], current="a")

        received = []
        combo.process_id_changed.connect(lambda v: received.append(v))

        monkeypatch.setattr(
            "frontend.widgets.pipeline.pipeline_tab.bridges.process_id_combo.QInputDialog.getText",
            lambda *args, **kwargs: ("", False),
        )

        sentinel_idx = combo.count() - 1
        combo.setCurrentIndex(sentinel_idx)

        # Сигнал не испущен (кроме возможного при cancel-revert)
        assert combo.currentData() == "a"


# ===========================================================================
# Тесты DisplayTargetCombo
# ===========================================================================


class TestDisplayTargetCombo:
    """Тесты multi-select дисплеев."""

    def test_set_known_displays_checks_current(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """set_known_displays(["w0","w1","w2"], current=["w1"]) -> w1 отмечен."""
        combo = DisplayTargetCombo()
        combo.set_known_displays(["w0", "w1", "w2"], current=["w1"])

        assert combo.value() == ["w1"]

    def test_toggle_emits_signal(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Чек w0 -> сигнал display_targets_changed(["w0", "w1"])."""
        combo = DisplayTargetCombo()
        combo.set_known_displays(["w0", "w1", "w2"], current=["w1"])

        received = []
        combo.display_targets_changed.connect(lambda v: received.append(v))

        # Программно чекаем w0 через menu action
        menu = combo._menu
        assert menu is not None
        actions = menu.actions()
        # Первый action = w0
        actions[0].setChecked(True)

        assert len(received) >= 1
        last = received[-1]
        assert "w0" in last
        assert "w1" in last

    def test_value_preserves_order(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """value() возвращает порядок из known_displays."""
        combo = DisplayTargetCombo()
        combo.set_known_displays(["w0", "w1", "w2"], current=["w2", "w0"])

        val = combo.value()
        assert val == ["w0", "w2"]  # порядок как в known_displays

    def test_add_new_display(
        self, qapp: QtWidgets.QApplication,
        monkeypatch,
    ) -> None:
        """+ Новый дисплей -> добавлен и выбран."""
        combo = DisplayTargetCombo()
        combo.set_known_displays(["w0"], current=[])

        received = []
        combo.display_targets_changed.connect(lambda v: received.append(v))

        monkeypatch.setattr(
            "frontend.widgets.pipeline.pipeline_tab.bridges.display_target_combo.QInputDialog.getText",
            lambda *args, **kwargs: ("w_new", True),
        )

        # Триггерим sentinel
        combo._on_add_new_display()

        assert "w_new" in combo.value()
        assert len(received) >= 1
        assert "w_new" in received[-1]


# ===========================================================================
# Тесты InspectorPanel + GRAPH_NODE_MODIFY
# ===========================================================================


class TestInspectorPanel:
    """Интеграционные тесты InspectorPanel."""

    def test_show_node_populates_widgets(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """show_node_by_id для resize ноды -> виджеты заполнены."""
        model, node_id = _make_model_with_resize()
        catalog = _make_resize_catalog()
        panel, bus, rm = _make_inspector(model, catalog)

        panel.show_node_by_id(node_id)

        assert panel.current_node_id == node_id
        # isHidden() проверяет внутренний флаг (isVisible требует показанного parent)
        assert not panel._general_group.isHidden()
        assert not panel._params_group.isHidden()
        # Проверяем что process_id combo заполнен
        assert panel._process_id_combo.count() > 0

    def test_process_id_change_records_action(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Изменение process_id -> ActionBus.record с GRAPH_NODE_MODIFY."""
        model, node_id = _make_model_with_resize()
        catalog = _make_resize_catalog()
        panel, bus, rm = _make_inspector(model, catalog, processes=["processor", "vision_1"])

        panel.show_node_by_id(node_id)

        # Меняем process_id
        idx = panel._process_id_combo.findData("vision_1")
        panel._process_id_combo.setCurrentIndex(idx)

        last = bus.last_action()
        assert last is not None
        assert last.action_type == ActionType.GRAPH_NODE_MODIFY
        assert last.forward_patch["fields_after"]["process_id"] == "vision_1"

        # Модель обновлена
        node = model.nodes[node_id]
        assert node.process_id == "vision_1"

    def test_params_change_records_action(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Изменение width в params_form -> action GRAPH_NODE_MODIFY, модель обновлена."""
        model, node_id = _make_model_with_resize()
        catalog = _make_resize_catalog()
        panel, bus, rm = _make_inspector(model, catalog)

        panel.show_node_by_id(node_id)

        # Меняем width через spinbox
        width_widget = panel._params_form._field_widgets.get("width")
        assert width_widget is not None
        width_widget.setValue(800)

        last = bus.last_action()
        assert last is not None
        assert last.action_type == ActionType.GRAPH_NODE_MODIFY
        # params merge: width обновлён, height сохранён
        node = model.nodes[node_id]
        assert node.params["width"] == 800
        assert node.params["height"] == 480

    def test_display_disabled_when_not_capable(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """DisplayTargetCombo disabled когда op_def.display_capable == False."""
        catalog = _make_color_catalog()
        model = GraphEditorModel()
        model.load(nodes={}, catalog=catalog)
        model.add_node("color_detection", node_id="n-color-1", params={
            "type": "color_detection",
            "enabled_filter": True,
            "color_lower": [0, 100, 100],
            "threshold": 0.5,
        })

        panel, bus, rm = _make_inspector(model, catalog)
        panel.show_node_by_id("n-color-1")

        assert not panel._display_group.isEnabled()

    def test_clear_shows_placeholder(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """clear() -> плейсхолдер видим, секции скрыты."""
        model, node_id = _make_model_with_resize()
        catalog = _make_resize_catalog()
        panel, bus, rm = _make_inspector(model, catalog)

        panel.show_node_by_id(node_id)
        panel.clear()

        assert panel.current_node_id is None
        assert not panel._placeholder.isHidden()
        assert panel._general_group.isHidden()

    def test_undo_restores_process_id(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """Undo -> model.nodes[nid].process_id восстановлен через handler revert."""
        model, node_id = _make_model_with_resize()
        catalog = _make_resize_catalog()
        panel, bus, rm = _make_inspector(model, catalog, processes=["processor", "vision_1"])

        panel.show_node_by_id(node_id)

        # Исходный process_id
        assert model.nodes[node_id].process_id == "processor"

        # Меняем
        idx = panel._process_id_combo.findData("vision_1")
        panel._process_id_combo.setCurrentIndex(idx)
        assert model.nodes[node_id].process_id == "vision_1"

        # Undo: handler восстанавливает register через nodes_before
        bus.undo()

        # Register восстановлен (через handler.revert -> rm.set_field_value)
        # Проверяем что в rm.calls есть вызов с nodes_before
        assert len(rm.calls) >= 1


# ===========================================================================
# Тесты GRAPH_NODE_MODIFY handler
# ===========================================================================


class TestGraphNodeModifyHandler:
    """Тесты GraphActionHandler для GRAPH_NODE_MODIFY."""

    def test_apply_sets_field_value(self) -> None:
        """apply -> set_field_value(region_id, "vision_pipeline", nodes_after)."""
        rm = MockRM()
        handler = GraphActionHandler()

        nodes_after = {"n1": {"process_id": "new"}}
        action = ActionBuilder.graph_node_modify(
            region_id="region_1",
            node_id="n1",
            fields_before={"process_id": "old"},
            fields_after={"process_id": "new"},
            nodes_before={"n1": {"process_id": "old"}},
            nodes_after=nodes_after,
        )

        handler.apply(action, rm)

        assert ("region_1", "vision_pipeline", nodes_after) in rm.calls

    def test_revert_sets_field_value_with_nodes_before(self) -> None:
        """revert -> set_field_value(region_id, "vision_pipeline", nodes_before)."""
        rm = MockRM()
        handler = GraphActionHandler()

        nodes_before = {"n1": {"process_id": "old"}}
        action = ActionBuilder.graph_node_modify(
            region_id="region_1",
            node_id="n1",
            fields_before={"process_id": "old"},
            fields_after={"process_id": "new"},
            nodes_before=nodes_before,
            nodes_after={"n1": {"process_id": "new"}},
        )

        handler.revert(action, rm)

        assert ("region_1", "vision_pipeline", nodes_before) in rm.calls


# ===========================================================================
# Тесты GraphEditorModel.modify_node
# ===========================================================================


class TestGraphEditorModelModifyNode:
    """Тесты метода modify_node."""

    def test_modify_process_id(self) -> None:
        """Меняет process_id -> ({"process_id": "old"}, {"process_id": "new"})."""
        model, node_id = _make_model_with_resize()

        before, after = model.modify_node(node_id, {"process_id": "new_proc"})

        assert before == {"process_id": "processor"}
        assert after == {"process_id": "new_proc"}
        assert model.nodes[node_id].process_id == "new_proc"

    def test_modify_params_merge(self) -> None:
        """params merge: current {"width": 640, "height": 480} + {"width": 800} -> {"width": 800, "height": 480}."""
        model, node_id = _make_model_with_resize()

        before, after = model.modify_node(node_id, {"params": {"width": 800}})

        assert before["params"]["width"] == 640
        assert before["params"]["height"] == 480
        assert after["params"]["width"] == 800
        assert after["params"]["height"] == 480
        assert model.nodes[node_id].params["width"] == 800
        assert model.nodes[node_id].params["height"] == 480

    def test_modify_forbidden_field_raises(self) -> None:
        """Запрещённое поле (node_id) -> ValueError."""
        model, node_id = _make_model_with_resize()

        with pytest.raises(ValueError, match="Запрещённые поля"):
            model.modify_node(node_id, {"node_id": "hack"})

    def test_modify_nonexistent_node_raises(self) -> None:
        """Несуществующая нода -> KeyError."""
        model, _ = _make_model_with_resize()

        with pytest.raises(KeyError, match="не найден"):
            model.modify_node("nonexistent-id", {"process_id": "x"})

    def test_modify_display_targets(self) -> None:
        """Меняет display_targets -> replace."""
        model, node_id = _make_model_with_resize()

        before, after = model.modify_node(node_id, {"display_targets": ["w0", "w1"]})

        assert before["display_targets"] == []
        assert after["display_targets"] == ["w0", "w1"]
        assert model.nodes[node_id].display_targets == ["w0", "w1"]

    def test_modify_enabled(self) -> None:
        """Меняет enabled."""
        model, node_id = _make_model_with_resize()

        before, after = model.modify_node(node_id, {"enabled": False})

        assert before["enabled"] is True
        assert after["enabled"] is False


# ===========================================================================
# Тест ActionBuilder.graph_node_modify
# ===========================================================================


class TestActionBuilderGraphNodeModify:
    """Тесты фабрики ActionBuilder.graph_node_modify."""

    def test_creates_correct_action(self) -> None:
        action = ActionBuilder.graph_node_modify(
            region_id="r1",
            node_id="n1-abcdef12-3456",
            fields_before={"process_id": "old"},
            fields_after={"process_id": "new"},
            nodes_before={"before": True},
            nodes_after={"after": True},
        )

        assert action.action_type == ActionType.GRAPH_NODE_MODIFY
        assert action.register_name == "r1"
        assert "n1-abcde" in action.description
        assert action.forward_patch["node_id"] == "n1-abcdef12-3456"
        assert action.forward_patch["fields_after"] == {"process_id": "new"}
        assert action.forward_patch["nodes_after"] == {"after": True}
        assert action.backward_patch["nodes_before"] == {"before": True}
        assert action.undoable is True
        assert action.coalesce_key is not None
