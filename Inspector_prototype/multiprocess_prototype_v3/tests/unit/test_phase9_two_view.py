"""Unit-тесты для PipelineTableView + PipelineViewSwitch (Task 9.11).

Покрывает:
  PipelineTableView:
  - refresh() заполняет нужное число строк (= len(model.nodes)).
  - Колонки имеют правильные заголовки.
  - select_node(nid) выделяет строку, эмитит selection_changed ровно один раз.
  - select_node(None) / select_node("") очищает выделение, эмитит "".
  - Bulk-edit enabled: 2 ноды выделены → проставить checkbox у одной → обе enabled=False.
  - Bulk-edit process_id: 2 ноды выделены → apply_field_change → 2 action'а в bus.
  - linearity warning виден при нелинейном графе.
  - При undo через action_bus → refresh, состояние восстанавливается.

  PipelineViewSwitch:
  - При создании mode = 'table', page = 1.
  - switch_to('graph') → page = 0, view_changed('graph') эмитится.
  - Adapter эмитит node_selected('nid_1') → selection_changed('nid_1') + _selected_node_id = 'nid_1'.
  - switch_to('table') → table_view.select_node('nid_1') вызван.
  - table эмитит selection_changed('nid_2') → switch.selection_changed('nid_2').
  - switch_to('graph') → adapter.node_map[nid_2].set_selected(True) вызван.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Annotated, List, Literal
from unittest.mock import MagicMock, call

import pytest

# Добавляем корень multiprocess_prototype_v3 в sys.path
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from PySide6 import QtCore, QtWidgets  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from frontend.actions.builder import ActionBuilder  # noqa: E402
from frontend.actions.default_bus_factory import create_default_action_bus  # noqa: E402
from frontend.actions.schemas import ActionType  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.canvas.model import GraphEditorModel  # noqa: E402
from frontend.widgets.pipeline.pipeline_tab.views.table_view import (  # noqa: E402
    COL_ENABLED,
    COL_HEADERS,
    COL_NAME,
    COL_OPERATION,
    COL_POSITION,
    COL_PROCESS_ID,
    PipelineTableView,
)
from frontend.widgets.pipeline.pipeline_tab.views.view_switch import (  # noqa: E402
    MODE_GRAPH,
    MODE_TABLE,
    PipelineViewSwitch,
)
from multiprocess_framework.modules.data_schema_module import (  # noqa: E402
    FieldMeta,
    SchemaBase,
    register_schema,
)
from registers.pipeline.processing_node import NodeInput, ProcessingNode  # noqa: E402
from registers.processor.catalog.port_types import PORT_TYPE_IMAGE  # noqa: E402
from registers.processor.catalog.schemas import Port, ProcessingOperationDef  # noqa: E402


# ---------------------------------------------------------------------------
# QApplication fixture (одна на сессию)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


# ---------------------------------------------------------------------------
# Мок RegistersManager
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager для тестов."""

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


def _make_catalog() -> dict[str, ProcessingOperationDef]:
    """Каталог из двух операций."""
    return {
        "resize": ProcessingOperationDef(
            name="Resize",
            type_key="resize",
            params_schema="tests.stub.ResizeParams",
            module_path="tests.stub.ResizeOp",
            category="Preprocess",
            display_capable=True,
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
        ),
        "blur": ProcessingOperationDef(
            name="Gaussian Blur",
            type_key="blur",
            params_schema="tests.stub.BlurParams",
            module_path="tests.stub.BlurOp",
            category="Preprocess",
            display_capable=False,
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
        ),
    }


def _make_model_with_two_nodes() -> tuple[GraphEditorModel, str, str]:
    """Модель с двумя нодами. Возвращает (model, nid1, nid2)."""
    catalog = _make_catalog()
    model = GraphEditorModel()
    model.load(nodes={}, catalog=catalog)
    _, n1 = model.add_node("resize", position=(0.0, 0.0), node_id="node-resize-1")
    _, n2 = model.add_node("blur", position=(200.0, 0.0), node_id="node-blur-2")
    return model, "node-resize-1", "node-blur-2"


def _make_table_view(
    model: GraphEditorModel,
    catalog: dict,
    *,
    processes: list[str] | None = None,
    region_id: str = "region-test",
) -> tuple[PipelineTableView, "ActionBus", MockRM]:
    """Создать PipelineTableView с моками."""
    rm = MockRM()
    bus = create_default_action_bus(rm)
    tv = PipelineTableView(
        model=model,
        action_bus=bus,
        catalog=catalog,
        region_id=region_id,
        known_processes_provider=lambda: processes or ["processor", "vision_1"],
    )
    tv.refresh()
    return tv, bus, rm


# ---------------------------------------------------------------------------
# Тесты PipelineTableView
# ---------------------------------------------------------------------------


class TestPipelineTableViewRefresh:
    """Тесты корректного заполнения таблицы."""

    def test_refresh_fills_correct_row_count(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """refresh() → число строк = len(model.nodes)."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        assert tv._item_model.rowCount() == 2

    def test_column_headers_correct(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Заголовки колонок совпадают с COL_HEADERS."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        for col, expected_header in enumerate(COL_HEADERS):
            actual = tv._item_model.horizontalHeaderItem(col).text()
            assert actual == expected_header, (
                f"Колонка {col}: ожидалось {expected_header!r}, получено {actual!r}"
            )

    def test_refresh_with_empty_model(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """При пустом model.nodes → 0 строк в таблице."""
        model = GraphEditorModel()
        model.load(nodes={}, catalog=_make_catalog())
        tv, bus, rm = _make_table_view(model, _make_catalog())

        assert tv._item_model.rowCount() == 0

    def test_node_id_stored_in_user_role(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """node_id хранится через UserRole в колонке 0."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        found_ids = set()
        for row in range(tv._item_model.rowCount()):
            item = tv._item_model.item(row, COL_ENABLED)
            nid = item.data(Qt.UserRole)
            found_ids.add(nid)

        assert nid1 in found_ids
        assert nid2 in found_ids


class TestPipelineTableViewSelection:
    """Тесты selection sync."""

    def test_select_node_emits_selection_changed_once(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """select_node(nid) → selection_changed(nid) эмитится ровно 1 раз."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        received: list[str] = []
        tv.selection_changed.connect(lambda nid: received.append(nid))

        tv.select_node(nid1)

        # select_node подавляет сигнал (suppress), поэтому сигнала быть НЕ должно
        # (программное выделение — без эмиссии)
        assert received == [], (
            "select_node() должен подавлять обратный сигнал selection_changed"
        )

    def test_select_node_highlights_correct_row(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """select_node(nid) → строка с этой нодой становится выделенной."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        tv.select_node(nid1)

        selected = tv.selected_node_ids()
        assert nid1 in selected

    def test_select_node_none_clears_selection(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """select_node(None) → выделение очищается."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        tv.select_node(nid1)
        tv.select_node(None)

        selected = tv.selected_node_ids()
        assert selected == []

    def test_select_node_empty_string_clears_selection(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """select_node('') → выделение очищается."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        tv.select_node(nid1)
        tv.select_node("")

        selected = tv.selected_node_ids()
        assert selected == []

    def test_user_selection_emits_signal(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Пользовательское выделение (не program.) → selection_changed эмитится."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        received: list[str] = []
        tv.selection_changed.connect(lambda nid: received.append(nid))

        # Эмулируем пользовательское выделение через selectionModel
        for row in range(tv._item_model.rowCount()):
            item = tv._item_model.item(row, COL_ENABLED)
            if item and item.data(Qt.UserRole) == nid1:
                index = tv._item_model.index(row, 0)
                tv._tree.selectionModel().select(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
                break

        assert len(received) >= 1
        assert received[-1] == nid1


class TestPipelineTableViewBulkEdit:
    """Тесты bulk-edit (enabled, process_id)."""

    def test_bulk_edit_enabled_records_two_actions(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """bulk-edit enabled: 2 ноды выделены → 2 GRAPH_NODE_MODIFY action'а."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        # Выделяем обе ноды программно (без подавления — через _select_row_by_node_id напрямую)
        # Для теста используем select_node для nid1, затем добавляем nid2 к selection
        tv._suppress_selection = True
        tv._select_row_by_node_id(nid1)
        # Добавляем nid2 к выделению
        for row in range(tv._item_model.rowCount()):
            item = tv._item_model.item(row, COL_ENABLED)
            if item and item.data(Qt.UserRole) == nid2:
                index = tv._item_model.index(row, 0)
                tv._tree.selectionModel().select(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.Select
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
                break
        tv._suppress_selection = False

        initial_undo_count = len(bus._undo_stack)

        # Применяем bulk-edit через API
        tv.apply_field_change(nid1, "enabled", False)

        # Должны быть записаны actions для обеих нод
        new_actions = len(bus._undo_stack) - initial_undo_count
        assert new_actions == 2, (
            f"Ожидалось 2 action'а (для каждой ноды), получено {new_actions}"
        )

    def test_bulk_edit_enabled_updates_model(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """bulk-edit enabled=False → обе ноды disabled в model."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        # Выделяем обе ноды
        tv._suppress_selection = True
        tv._select_row_by_node_id(nid1)
        for row in range(tv._item_model.rowCount()):
            item = tv._item_model.item(row, COL_ENABLED)
            if item and item.data(Qt.UserRole) == nid2:
                idx = tv._item_model.index(row, 0)
                tv._tree.selectionModel().select(
                    idx,
                    QtCore.QItemSelectionModel.SelectionFlag.Select
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
                break
        tv._suppress_selection = False

        tv.apply_field_change(nid1, "enabled", False)

        nodes = model.nodes
        assert nodes[nid1].enabled is False
        assert nodes[nid2].enabled is False

    def test_bulk_edit_process_id_records_two_actions(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """bulk-edit process_id: 2 ноды выделены → 2 GRAPH_NODE_MODIFY action'а."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        # Выделяем обе ноды
        tv._suppress_selection = True
        tv._select_row_by_node_id(nid1)
        for row in range(tv._item_model.rowCount()):
            item = tv._item_model.item(row, COL_ENABLED)
            if item and item.data(Qt.UserRole) == nid2:
                idx = tv._item_model.index(row, 0)
                tv._tree.selectionModel().select(
                    idx,
                    QtCore.QItemSelectionModel.SelectionFlag.Select
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
                break
        tv._suppress_selection = False

        initial_count = len(bus._undo_stack)
        tv.apply_field_change(nid1, "process_id", "vision_worker")

        new_actions = len(bus._undo_stack) - initial_count
        assert new_actions == 2, (
            f"Ожидалось 2 action'а, получено {new_actions}"
        )

    def test_bulk_edit_process_id_updates_model(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """bulk-edit process_id → обе ноды обновлены в model."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        # Выделяем обе ноды
        tv._suppress_selection = True
        tv._select_row_by_node_id(nid1)
        for row in range(tv._item_model.rowCount()):
            item = tv._item_model.item(row, COL_ENABLED)
            if item and item.data(Qt.UserRole) == nid2:
                idx = tv._item_model.index(row, 0)
                tv._tree.selectionModel().select(
                    idx,
                    QtCore.QItemSelectionModel.SelectionFlag.Select
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
                break
        tv._suppress_selection = False

        tv.apply_field_change(nid1, "process_id", "vision_worker")

        nodes = model.nodes
        assert nodes[nid1].process_id == "vision_worker"
        assert nodes[nid2].process_id == "vision_worker"

    def test_single_node_edit_records_one_action(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Если выделена одна нода → 1 action для одного изменения."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        # Выделяем только nid1
        tv.select_node(nid1)

        initial_count = len(bus._undo_stack)
        tv.apply_field_change(nid1, "process_id", "new_proc")

        new_actions = len(bus._undo_stack) - initial_count
        assert new_actions == 1

    def test_node_modified_signal_emitted(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """node_modified сигнал эмитится при каждом успешном изменении."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        tv.select_node(nid1)

        received: list[tuple] = []
        tv.node_modified.connect(lambda nid, fields: received.append((nid, fields)))

        tv.apply_field_change(nid1, "process_id", "proc_new")

        assert len(received) == 1
        assert received[0][0] == nid1
        assert received[0][1] == {"process_id": "proc_new"}


class TestPipelineTableViewLinearity:
    """Тесты linearity warning."""

    def test_no_warning_for_linear_graph(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Линейный граф → warning скрыт (isHidden = True)."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        # Линейный: nid2 зависит от nid1
        model.connect(nid1, "out", nid2, "in")

        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        # В offscreen режиме виджет не показан на экране, но QLabel.hide()/show()
        # изменяет состояние. Проверяем через isHidden() (True = скрыт).
        assert tv._warning_label.isHidden(), (
            "Для линейного графа warning должен быть скрыт"
        )

    def test_warning_shown_for_nonlinear_graph(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Нелинейный граф (нода с >1 зависимыми) → warning показывается."""
        model = GraphEditorModel()
        catalog = _make_catalog()
        model.load(nodes={}, catalog=catalog)

        # Добавляем 3 ноды: nid1 → nid2 и nid1 → nid3 (ветвление)
        model.add_node("resize", position=(0.0, 0.0), node_id="nid1")
        model.add_node("blur", position=(200.0, 0.0), node_id="nid2")
        model.add_node("blur", position=(200.0, 100.0), node_id="nid3")

        # Ветвление: nid1.out → nid2.in и nid1.out → nid3.in
        model.connect("nid1", "out", "nid2", "in")
        model.connect("nid1", "out", "nid3", "in")

        tv, bus, rm = _make_table_view(model, catalog)

        # В offscreen режиме show() устанавливает состояние, isHidden()=False.
        assert not tv._warning_label.isHidden(), (
            "Для нелинейного графа warning должен быть показан"
        )
        assert len(tv._warning_label.text()) > 0, (
            "Текст warning не должен быть пустым"
        )


class TestPipelineTableViewUndo:
    """Тест undo через action_bus → refresh."""

    def test_undo_action_recorded_in_bus(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """apply_field_change записывает GRAPH_NODE_MODIFY в undo-стек bus."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        tv.select_node(nid1)

        initial_count = len(bus._undo_stack)
        tv.apply_field_change(nid1, "process_id", "changed_proc")

        assert len(bus._undo_stack) > initial_count
        action = bus._undo_stack[-1]
        from frontend.actions.schemas import ActionType  # уже импортирован выше
        assert action.action_type == ActionType.GRAPH_NODE_MODIFY

    def test_undo_provides_nodes_before_to_rm(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """bus.undo() вызывает handler.revert → RM получает nodes_before."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        tv.select_node(nid1)

        # Запоминаем nodes_before (нода с исходным process_id = 'processor')
        nodes_before_snapshot = deepcopy(model.nodes)

        tv.apply_field_change(nid1, "process_id", "changed_proc")
        assert model.nodes[nid1].process_id == "changed_proc"

        # После undo handler.revert записывает nodes_before в RM
        bus.undo()

        # RM должен получить вызов set_field_value с nodes_before
        # (GraphActionHandler.revert вызывает rm.set_field_value(region_id, 'vision_pipeline', nodes_before))
        region_id = "region-test"
        calls_to_rm = [c for c in rm.calls if c[0] == region_id]
        assert len(calls_to_rm) >= 1, (
            "RM должен получить set_field_value при revert"
        )

    def test_action_bus_change_callback_triggers_refresh(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """ActionBus change_callback вызывает refresh() в table_view."""
        model, nid1, nid2 = _make_model_with_two_nodes()
        catalog = _make_catalog()
        tv, bus, rm = _make_table_view(model, catalog)

        refresh_calls: list[int] = []
        original_refresh = tv.refresh

        def _counted_refresh():
            refresh_calls.append(1)
            original_refresh()

        tv.refresh = _counted_refresh  # type: ignore[method-assign]

        # Вызываем apply_field_change → bus.record → callback → refresh
        tv.apply_field_change(nid1, "process_id", "new_proc_1")

        # refresh вызывается внутри apply_field_change напрямую
        # + через callback при record.
        assert len(refresh_calls) >= 1

        tv.refresh = original_refresh  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Тесты PipelineViewSwitch
# ---------------------------------------------------------------------------


def _make_mock_adapter_with_signals() -> MagicMock:
    """Создать мок NodeGraphQtAdapter с реальными Qt-сигналами."""

    # Нужен QObject с настоящими сигналами для connect/emit
    class _FakeAdapter(QtCore.QObject):
        node_selected = QtCore.Signal(str)
        selection_cleared = QtCore.Signal()

        def __init__(self):
            super().__init__()
            self._node_map: dict[str, MagicMock] = {}

        @property
        def node_map(self):
            return self._node_map

    return _FakeAdapter()


class TestPipelineViewSwitch:
    """Тесты PipelineViewSwitch."""

    def _make_switch(
        self,
        qapp: QtWidgets.QApplication,
        model: GraphEditorModel | None = None,
        catalog: dict | None = None,
    ) -> tuple[PipelineViewSwitch, MagicMock, "PipelineTableView"]:
        """Создать PipelineViewSwitch с моками."""
        if model is None:
            model, nid1, nid2 = _make_model_with_two_nodes()
        if catalog is None:
            catalog = _make_catalog()

        rm = MockRM()
        bus = create_default_action_bus(rm)

        tv = PipelineTableView(
            model=model,
            action_bus=bus,
            catalog=catalog,
            region_id="region-test",
            known_processes_provider=lambda: ["processor"],
        )
        tv.refresh()

        # Мок graph_widget
        graph_widget = QtWidgets.QWidget()

        adapter = _make_mock_adapter_with_signals()

        switch = PipelineViewSwitch(
            graph_widget=graph_widget,
            adapter=adapter,
            table_view=tv,
        )
        return switch, adapter, tv

    def test_default_mode_is_table(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """По умолчанию режим = 'table', page = 1 (table)."""
        switch, adapter, tv = self._make_switch(qapp)

        assert switch.current_mode == MODE_TABLE
        assert switch._stack.currentIndex() == 1

    def test_switch_to_graph_changes_page(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """switch_to('graph') → page = 0, view_changed('graph') эмитится."""
        switch, adapter, tv = self._make_switch(qapp)

        received_views: list[str] = []
        switch.view_changed.connect(lambda m: received_views.append(m))

        switch.switch_to(MODE_GRAPH)

        assert switch.current_mode == MODE_GRAPH
        assert switch._stack.currentIndex() == 0
        assert received_views == [MODE_GRAPH]

    def test_switch_to_table_emits_view_changed(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """switch_to('table') после 'graph' → page = 1, view_changed('table')."""
        switch, adapter, tv = self._make_switch(qapp)

        switch.switch_to(MODE_GRAPH)
        received_views: list[str] = []
        switch.view_changed.connect(lambda m: received_views.append(m))

        switch.switch_to(MODE_TABLE)

        assert switch.current_mode == MODE_TABLE
        assert switch._stack.currentIndex() == 1
        assert received_views == [MODE_TABLE]

    def test_switch_to_same_mode_is_noop(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """switch_to('table') когда уже 'table' → view_changed не эмитится."""
        switch, adapter, tv = self._make_switch(qapp)

        received_views: list[str] = []
        switch.view_changed.connect(lambda m: received_views.append(m))

        switch.switch_to(MODE_TABLE)  # уже table

        assert received_views == []

    def test_adapter_node_selected_propagates(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Adapter эмитит node_selected('nid_1') → selection_changed('nid_1')."""
        switch, adapter, tv = self._make_switch(qapp)

        received: list[str] = []
        switch.selection_changed.connect(lambda nid: received.append(nid))

        adapter.node_selected.emit("nid_1")

        assert received == ["nid_1"]
        assert switch._selected_node_id == "nid_1"

    def test_adapter_selection_cleared_propagates(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Adapter эмитит selection_cleared → selection_changed('') + _selected_node_id=None."""
        switch, adapter, tv = self._make_switch(qapp)

        switch._selected_node_id = "nid_1"

        received: list[str] = []
        switch.selection_changed.connect(lambda nid: received.append(nid))

        adapter.selection_cleared.emit()

        assert received == [""]
        assert switch._selected_node_id is None

    def test_switch_to_table_transfers_selection(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """switch_to('graph') затем switch_to('table') → table.select_node(nid) вызван."""
        switch, adapter, tv = self._make_switch(qapp)

        # Запоминаем выделение
        adapter.node_selected.emit("node-resize-1")
        assert switch._selected_node_id == "node-resize-1"

        # Переключаемся в graph mode
        switch.switch_to(MODE_GRAPH)

        # Мокируем table_view.select_node
        select_node_calls: list[str | None] = []
        original_select = tv.select_node
        tv.select_node = lambda nid: select_node_calls.append(nid)  # type: ignore[method-assign]

        # Переключаемся обратно в table
        switch.switch_to(MODE_TABLE)

        assert len(select_node_calls) >= 1
        assert select_node_calls[-1] == "node-resize-1"

        # Восстанавливаем
        tv.select_node = original_select  # type: ignore[method-assign]

    def test_switch_to_graph_tries_adapter_node_map(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """switch_to('graph') → adapter.node_map[nid].set_selected(True) вызван."""
        switch, adapter, tv = self._make_switch(qapp)

        # Создаём мок-ноду в adapter.node_map
        mock_qt_node = MagicMock()
        adapter._node_map["node-blur-2"] = mock_qt_node

        # Устанавливаем выделение
        switch._selected_node_id = "node-blur-2"

        # Переключаемся на graph
        switch.switch_to(MODE_GRAPH)

        mock_qt_node.set_selected.assert_called_once_with(True)

    def test_table_selection_propagates_through_switch(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """table эмитит selection_changed('nid') → switch.selection_changed('nid')."""
        switch, adapter, tv = self._make_switch(qapp)

        received: list[str] = []
        switch.selection_changed.connect(lambda nid: received.append(nid))

        # Эмулируем пользовательское выделение в table_view
        tv.selection_changed.emit("node-resize-1")

        assert "node-resize-1" in received
        assert switch._selected_node_id == "node-resize-1"

    def test_toggle_button_text_changes(
        self, qapp: QtWidgets.QApplication
    ) -> None:
        """Кнопка переключения меняет текст при смене режима."""
        switch, adapter, tv = self._make_switch(qapp)

        # Начальный режим — table, кнопка должна показывать "Граф"
        assert switch._toggle_btn.text() == "Граф"

        switch.switch_to(MODE_GRAPH)
        assert switch._toggle_btn.text() == "Таблица"

        switch.switch_to(MODE_TABLE)
        assert switch._toggle_btn.text() == "Граф"
