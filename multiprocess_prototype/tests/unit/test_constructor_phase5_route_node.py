"""Тесты Фазы 5 конструктора — ShmRouteNode и auto-insert логика.

Тесты:
1. test_route_node_type_constant       — ROUTE_NODE_TYPE == "constructor.nodes.ShmRouteNode"
2. test_route_node_set_route_data      — set_route_data создаёт N выходных портов
3. test_route_node_add_fan_out_port    — add_fan_out_port добавляет порт
4. test_route_node_remove_fan_out_port — remove_fan_out_port удаляет порт
5. test_builder_returns_three_tuple    — GraphBuilder.build() возвращает 3 элемента
6. test_count_outgoing_wires           — _count_outgoing_wires корректно считает
7. test_adapter_route_nodes_init_empty — _route_nodes пустой при создании
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Заглушки для circular import — паттерн из test_constructor_phase3.py
# ---------------------------------------------------------------------------

_STUB_MODULES = [
    # tabs_setting circular stubs
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab.camera_panel",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_settings_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.display_tab",
    # base leaf-stubs — только проблемные, пакет base остаётся реальным
    "multiprocess_prototype.frontend.widgets.base.recipe_panel_base",
    "multiprocess_prototype.frontend.widgets.base.navigation_panel_base",
    "multiprocess_prototype.frontend.widgets.base.cards_field_factory",
    # coordinators и touch_keyboard
    "multiprocess_prototype.frontend.coordinators",
    "multiprocess_prototype.frontend.touch_keyboard_bind",
    # recipes stubs
    "multiprocess_prototype.frontend.widgets.recipes",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget.panel_widget",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget.schemas",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget.auto_save",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget.slot_combo_model",
    # NodeGraphQt — недоступен в тестовом окружении без GUI
    "NodeGraphQt",
    "NodeGraphQt.qgraphics",
    "NodeGraphQt.qgraphics.node_base",
]
for _mod in _STUB_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# После регистрации заглушек NodeGraphQt создаём фиктивный BaseNode
# чтобы ShmRouteNode мог от него унаследоваться корректно
_mock_ngq = sys.modules["NodeGraphQt"]
_mock_ngq.BaseNode = MagicMock
_mock_ngq.qgraphics = MagicMock()
_mock_ngq.qgraphics.node_base = MagicMock()
_mock_ngq.qgraphics.node_base.NodeItem = MagicMock


# ---------------------------------------------------------------------------
# Импорты тестируемых модулей (после регистрации заглушек)
# ---------------------------------------------------------------------------

from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.shm_route_node import (  # noqa: E402
    ROUTE_NODE_TYPE,
    ShmRouteNode,
)


# ===========================================================================
# Вспомогательные фабрики
# ===========================================================================

def _make_mock_node() -> MagicMock:
    """Создать mock-объект для ShmRouteNode без spec (BaseNode замокан).

    Используем MagicMock() без spec — иначе атрибуты типа get_property
    будут заблокированы spec'ом (ShmRouteNode сам унаследован от MagicMock).
    """
    node = MagicMock()
    # Хранилище свойств — как в реальном BaseNode
    _props: dict = {}
    node.get_property.side_effect = lambda k: _props.get(k, "")
    node.set_property.side_effect = lambda k, v: _props.update({k: v})
    # output_ports() — список портов (mutable)
    _ports: list = []
    node.output_ports.side_effect = lambda: list(_ports)
    node.add_output.side_effect = lambda name, **kw: _ports.append(MagicMock(**{"name.return_value": name}))
    node.delete_output.side_effect = lambda p: _ports.remove(p) if p in _ports else None
    node.view = MagicMock()
    return node


# ===========================================================================
# Test 1 — ROUTE_NODE_TYPE константа
# ===========================================================================

class TestRouteNodeTypeConstant:
    """ROUTE_NODE_TYPE должен быть строго "constructor.nodes.ShmRouteNode"."""

    def test_route_node_type_constant(self) -> None:
        """ROUTE_NODE_TYPE == "constructor.nodes.ShmRouteNode"."""
        assert ROUTE_NODE_TYPE == "constructor.nodes.ShmRouteNode"


# ===========================================================================
# Test 2 — set_route_data создаёт N выходных портов
# ===========================================================================

class TestShmRouteNodeSetRouteData:
    """set_route_data(route_key, shm_name, output_count) — установить данные.

    Патчим RouteNodeItem в модуле shm_route_node, чтобы isinstance() работал
    с MagicMock (который не является настоящим классом после стаббинга NodeGraphQt).
    """

    def setup_method(self) -> None:
        """Создать mock-ноду с нужными атрибутами."""
        self.node = _make_mock_node()

    def _call_set_route_data(self, *args) -> None:
        """Вызвать set_route_data с патченным RouteNodeItem."""
        import multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.shm_route_node as _mod
        # Патчим RouteNodeItem так, чтобы isinstance всегда возвращал False
        # (view — обычный MagicMock, не RouteNodeItem)
        original = _mod.RouteNodeItem
        _mod.RouteNodeItem = type("RouteNodeItem", (), {})  # пустой класс
        try:
            ShmRouteNode.set_route_data(self.node, *args)
        finally:
            _mod.RouteNodeItem = original

    def test_set_route_data_stores_route_key(self) -> None:
        """route_key сохраняется через set_property."""
        self._call_set_route_data("cam.capture.frame", "cam__capture__frame", 2)
        self.node.set_property.assert_any_call("route_key", "cam.capture.frame")

    def test_set_route_data_stores_shm_name(self) -> None:
        """shm_name сохраняется через set_property."""
        self._call_set_route_data("cam.capture.frame", "cam__capture__frame", 2)
        self.node.set_property.assert_any_call("shm_name", "cam__capture__frame")

    def test_set_route_data_creates_correct_output_count(self) -> None:
        """set_route_data создаёт ровно output_count выходных портов."""
        self._call_set_route_data("cam.capture.frame", "cam__capture__frame", 3)
        # add_output вызван 3 раза: out_1, out_2, out_3
        assert self.node.add_output.call_count == 3

    def test_set_route_data_output_names_follow_pattern(self) -> None:
        """Порты называются out_1, out_2, out_3 ..."""
        self._call_set_route_data("x.y.z", "x__y__z", 2)
        calls = [c[0][0] for c in self.node.add_output.call_args_list]
        assert calls == ["out_1", "out_2"]

    def test_set_route_data_zero_outputs(self) -> None:
        """output_count=0 — не создаёт ни одного порта."""
        self._call_set_route_data("x.y.z", "x__y__z", 0)
        self.node.add_output.assert_not_called()


# ===========================================================================
# Test 3 — add_fan_out_port
# ===========================================================================

class TestShmRouteNodeAddFanOutPort:
    """add_fan_out_port(name) добавляет выходной порт."""

    def setup_method(self) -> None:
        self.node = _make_mock_node()

    def test_add_fan_out_port_named(self) -> None:
        """add_fan_out_port с явным именем — add_output вызывается с этим именем."""
        ShmRouteNode.add_fan_out_port(self.node, "my_port")
        self.node.add_output.assert_called_once_with("my_port")

    def test_add_fan_out_port_auto_name_when_empty(self) -> None:
        """add_fan_out_port('') — имя порта автоматически out_{N+1}."""
        # output_ports() уже вернёт 2 элемента — имитируем существующие порты
        existing = [MagicMock(), MagicMock()]
        self.node.output_ports.side_effect = lambda: list(existing)
        ShmRouteNode.add_fan_out_port(self.node, "")
        # При 2 существующих портах следующий должен быть out_3
        self.node.add_output.assert_called_once_with("out_3")

    def test_add_fan_out_port_auto_name_no_existing(self) -> None:
        """add_fan_out_port('') при 0 портах → out_1."""
        self.node.output_ports.side_effect = lambda: []
        ShmRouteNode.add_fan_out_port(self.node, "")
        self.node.add_output.assert_called_once_with("out_1")


# ===========================================================================
# Test 4 — remove_fan_out_port
# ===========================================================================

class TestShmRouteNodeRemoveFanOutPort:
    """remove_fan_out_port(name) удаляет порт по имени."""

    def setup_method(self) -> None:
        self.node = _make_mock_node()

    def test_remove_fan_out_port_existing(self) -> None:
        """remove_fan_out_port по существующему имени — delete_output вызывается."""
        port = MagicMock()
        port.name.return_value = "out_2"
        self.node.output_ports.side_effect = lambda: [port]
        ShmRouteNode.remove_fan_out_port(self.node, "out_2")
        self.node.delete_output.assert_called_once_with(port)

    def test_remove_fan_out_port_missing(self) -> None:
        """remove_fan_out_port для несуществующего имени — delete_output не вызывается."""
        port = MagicMock()
        port.name.return_value = "out_1"
        self.node.output_ports.side_effect = lambda: [port]
        ShmRouteNode.remove_fan_out_port(self.node, "out_999")
        self.node.delete_output.assert_not_called()

    def test_remove_fan_out_port_first_matching_only(self) -> None:
        """Удаляется только первый найденный порт с нужным именем."""
        port1 = MagicMock()
        port1.name.return_value = "out_1"
        port2 = MagicMock()
        port2.name.return_value = "out_2"
        self.node.output_ports.side_effect = lambda: [port1, port2]
        ShmRouteNode.remove_fan_out_port(self.node, "out_1")
        self.node.delete_output.assert_called_once_with(port1)


# ===========================================================================
# Test 5 — GraphBuilder.build() возвращает 3-tuple
# ===========================================================================

class TestGraphBuilderReturnsTuple:
    """GraphBuilder.build() должен вернуть (node_map, addr_to_wire_key, route_nodes)."""

    def test_builder_returns_three_tuple(self) -> None:
        """build() возвращает кортеж из 3 элементов."""
        # Stub NodeGraphQt на уровне модуля graph_builder
        mock_graph = MagicMock()
        mock_graph.all_nodes.return_value = []
        # create_node возвращает MagicMock (не PluginProcessNode) — graceful skip
        mock_graph.create_node.return_value = MagicMock()

        # cross_model с пустым process_nodes
        mock_cross_model = MagicMock()
        mock_cross_model.process_nodes = {}

        # Патчим auto_layout чтобы не требовал Qt
        with patch(
            "multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.graph_builder.auto_layout",
            return_value={},
        ):
            from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.graph_builder import (
                GraphBuilder,
            )

            builder = GraphBuilder(mock_graph)
            result = builder.build(mock_cross_model, wires={})

        assert isinstance(result, tuple), "build() должен возвращать tuple"
        assert len(result) == 4, "build() должен возвращать 4 элемента"

    def test_builder_returns_empty_maps_for_empty_input(self) -> None:
        """build() с пустыми данными возвращает пустые словари."""
        mock_graph = MagicMock()
        mock_graph.all_nodes.return_value = []

        mock_cross_model = MagicMock()
        mock_cross_model.process_nodes = {}

        with patch(
            "multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.graph_builder.auto_layout",
            return_value={},
        ):
            from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.graph_builder import (
                GraphBuilder,
            )

            builder = GraphBuilder(mock_graph)
            node_map, addr_to_wire_key, route_nodes, display_nodes = builder.build(mock_cross_model, wires={})

        assert node_map == {}
        assert addr_to_wire_key == {}
        assert route_nodes == {}
        assert display_nodes == {}


# ===========================================================================
# Test 6 — _count_outgoing_wires
# ===========================================================================

class TestCountOutgoingWires:
    """_count_outgoing_wires(source_addr) — подсчёт fan-out по _addr_wire_map.

    Тестируем как чистую функцию: передаём mock-объект с нужным _addr_wire_map.
    PluginGraphAdapter наследует QObject, поэтому object.__new__() запрещён.
    Используем простой MagicMock с атрибутом _addr_wire_map.
    """

    def _make_fake_self(self, addr_wire_map: dict) -> MagicMock:
        """Создать fake self с _addr_wire_map для вызова метода."""
        fake = MagicMock()
        fake._addr_wire_map = dict(addr_wire_map)
        return fake

    def test_count_outgoing_wires_zero(self) -> None:
        """Нет wires для source — возвращает 0."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        fake_self = self._make_fake_self({})
        result = PluginGraphAdapter._count_outgoing_wires(fake_self, "cam.capture.frame")
        assert result == 0

    def test_count_outgoing_wires_one(self) -> None:
        """Один wire от source — возвращает 1."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        fake_self = self._make_fake_self({
            ("cam.capture.frame", "proc.mask.frame"): "wire_1",
        })
        result = PluginGraphAdapter._count_outgoing_wires(fake_self, "cam.capture.frame")
        assert result == 1

    def test_count_outgoing_wires_fan_out(self) -> None:
        """Два wire от одного source — возвращает 2 (fan-out)."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        fake_self = self._make_fake_self({
            ("cam.capture.frame", "proc1.mask.frame"): "wire_1",
            ("cam.capture.frame", "proc2.mask.frame"): "wire_2",
            ("other.src.data", "proc3.inp.data"): "wire_3",
        })
        result = PluginGraphAdapter._count_outgoing_wires(fake_self, "cam.capture.frame")
        assert result == 2

    def test_count_outgoing_wires_does_not_count_other_sources(self) -> None:
        """Wires от другого source не попадают в подсчёт."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        fake_self = self._make_fake_self({
            ("cam.capture.frame", "proc1.mask.frame"): "wire_1",
            ("other.plugin.port", "proc2.inp.data"): "wire_2",
        })
        result = PluginGraphAdapter._count_outgoing_wires(fake_self, "other.plugin.port")
        assert result == 1


# ===========================================================================
# Test 7 — _route_nodes пустой при создании
# ===========================================================================

class TestAdapterRouteNodesInitEmpty:
    """_route_nodes должен быть пустым словарём при создании адаптера.

    PluginGraphAdapter наследует QObject — object.__new__ запрещён.
    Проверяем атрибут через анализ исходного кода __init__:
    в __init__ обязательно присутствует self._route_nodes = {}.
    Используем inspect для проверки логики инициализации.
    """

    def test_adapter_route_nodes_init_empty(self) -> None:
        """В __init__ PluginGraphAdapter _route_nodes инициализируется как {}."""
        import inspect
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        # Получаем исходный код __init__ и проверяем инициализацию _route_nodes
        source = inspect.getsource(PluginGraphAdapter.__init__)
        assert "_route_nodes" in source, "_route_nodes должен быть в __init__"
        assert "_route_nodes: dict" in source or "self._route_nodes = {}" in source, (
            "_route_nodes должен инициализироваться пустым словарём"
        )

    def test_adapter_route_nodes_attr_is_dict_type(self) -> None:
        """_route_nodes инициализируется как dict (пустой) согласно исходному коду.

        В коде используется аннотированное присваивание:
        self._route_nodes: dict[str, ShmRouteNode] = {}
        Ищем оба паттерна — с и без аннотации типа.
        """
        import inspect
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        source = inspect.getsource(PluginGraphAdapter.__init__)
        # Аннотированное присваивание: self._route_nodes: dict[...] = {}
        has_annotated = "_route_nodes:" in source and "= {}" in source
        # Простое присваивание: self._route_nodes = {}
        has_plain = "self._route_nodes = {}" in source
        assert has_annotated or has_plain, (
            "self._route_nodes должен инициализироваться пустым dict в __init__"
        )
