# -*- coding: utf-8 -*-
"""Характеризационные тесты codec топология↔граф (Трек F, Task F.1).

Фиксируют ТЕКУЩЕЕ поведение конвертера `PipelinePresenter._topology_to_graph`
и обратной сериализации `io.graph_to_blueprint` ДО разреза god-файла presenter.

Цель — не «улучшить», а заморозить наблюдаемое поведение (включая странности:
суффикс `#i` у дублей, subtitle «(пусто)» у процесса без плагинов, дедуп боксов
по display_id, приоритет позиций node_id > anchor процесса > дефолтный кластер).
После выноса `TopologyGraphCodec` (Task F.2) эти тесты должны пройти без правок
ожиданий — они и есть контракт разреза.

Тесты headless: presenter создаётся на fake-services без Qt-сцены, вызывается
чистый метод `_topology_to_graph(topo_dict)` (как в test_yaml_positions).
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.domain.protocols.plugin_catalog import PluginSpec, PortSpec
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.constants import (
    CONTAINER_HEADER_H,
    CONTAINER_INNER_GAP,
    CONTAINER_PADDING,
    NODE_WIDTH,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services


# --------------------------------------------------------------------------- #
#  Фабрики                                                                     #
# --------------------------------------------------------------------------- #


def _presenter(topology, plugin_specs=None):
    """Headless presenter на fake-services с заданной топологией и каталогом плагинов."""
    services = make_pipeline_services(topology=topology, plugin_specs=plugin_specs)
    return PipelinePresenter(services)


def _spec(name, category="utility", ports=()):
    return PluginSpec(name=name, category=category, ports=tuple(ports))


def _by_id(nodes):
    return {n.node_id: n for n in nodes}


# --------------------------------------------------------------------------- #
#  Ноды: базовые случаи                                                        #
# --------------------------------------------------------------------------- #


class TestNodesBasic:
    def test_single_plugin_process(self):
        """Процесс с 1 плагином → одна плагин-нода node_id=`{proc}.{plugin}`."""
        topo = {"processes": [{"process_name": "cam", "plugins": [{"plugin_name": "capture"}]}], "wires": []}
        p = _presenter(topo, plugin_specs={"capture": _spec("capture", category="source")})

        nodes, edges = p._topology_to_graph(topo)

        assert len(nodes) == 1
        node = nodes[0]
        assert node.node_id == "cam.capture"
        assert node.title == "capture"
        assert node.category == "source"
        assert node.process_name == "cam"
        assert node.plugin_index == 0
        assert node.plugin_name == "capture"
        assert node.locked is False
        assert edges == []

    def test_chain_three_plugins_implicit_edges(self):
        """Цепочка 3 плагинов → 2 неявные стрелки между соседями (implicit=True)."""
        topo = {
            "processes": [
                {"process_name": "proc", "plugins": [{"plugin_name": "a"}, {"plugin_name": "b"}, {"plugin_name": "c"}]}
            ],
            "wires": [],
        }
        p = _presenter(topo, plugin_specs={n: _spec(n) for n in "abc"})

        nodes, edges = p._topology_to_graph(topo)

        assert [n.node_id for n in nodes] == ["proc.a", "proc.b", "proc.c"]
        assert [n.plugin_index for n in nodes] == [0, 1, 2]
        assert len(edges) == 2
        assert all(e.implicit for e in edges)
        assert (edges[0].source_id, edges[0].target_id) == ("proc.a", "proc.b")
        assert (edges[1].source_id, edges[1].target_id) == ("proc.b", "proc.c")

    def test_process_without_plugins_fallback_node(self):
        """Процесс без плагинов → fallback-нода plugin_index=-1, subtitle «(пусто)»."""
        topo = {"processes": [{"process_name": "empty", "plugins": []}], "wires": []}
        p = _presenter(topo)

        nodes, edges = p._topology_to_graph(topo)

        assert len(nodes) == 1
        node = nodes[0]
        assert node.node_id == "empty"
        assert node.title == "empty"
        assert node.subtitle == "(пусто)"
        assert node.category == "utility"
        assert node.plugin_index == -1
        assert node.plugin_name == ""
        assert edges == []

    def test_protected_process_not_drawn(self):
        """protected: true → процесс не рисуется вовсе."""
        topo = {
            "processes": [
                {"process_name": "gui", "protected": True, "plugins": [{"plugin_name": "x"}]},
                {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
            ],
            "wires": [],
        }
        p = _presenter(topo, plugin_specs={"x": _spec("x"), "capture": _spec("capture")})

        nodes, _edges = p._topology_to_graph(topo)

        ids = {n.node_id for n in nodes}
        assert ids == {"cam.capture"}
        assert not any(n.process_name == "gui" for n in nodes)

    def test_duplicate_plugin_name_gets_suffix(self):
        """Дубликат plugin_name в одном процессе → суффикс `#i`, первое вхождение без суффикса."""
        topo = {
            "processes": [{"process_name": "p", "plugins": [{"plugin_name": "dup"}, {"plugin_name": "dup"}]}],
            "wires": [],
        }
        p = _presenter(topo, plugin_specs={"dup": _spec("dup")})

        nodes, _edges = p._topology_to_graph(topo)

        assert [n.node_id for n in nodes] == ["p.dup", "p.dup#1"]


# --------------------------------------------------------------------------- #
#  Порты плагина (кэш)                                                          #
# --------------------------------------------------------------------------- #


class TestPortSchemasCache:
    def test_port_schemas_cached_per_node(self):
        """port_schemas плагина реконструируются из spec.ports и кэшируются по node_id."""
        ports = [
            PortSpec(name="frame", dtype="image/bgr", direction="input", optional=False),
            PortSpec(name="mask", dtype="image/mask", direction="output", optional=True),
        ]
        topo = {"processes": [{"process_name": "proc", "plugins": [{"plugin_name": "seg"}]}], "wires": []}
        p = _presenter(topo, plugin_specs={"seg": _spec("seg", category="processing", ports=ports)})

        p._topology_to_graph(topo)

        cache = p._port_schemas_cache
        assert set(cache) == {"proc.seg"}
        schemas = cache["proc.seg"]
        assert [(s.name, s.direction, s.dtype, s.optional) for s in schemas] == [
            ("frame", "input", "image/bgr", False),
            ("mask", "output", "image/mask", True),
        ]

    def test_no_ports_not_cached(self):
        """Плагин без портов → node_id отсутствует в _port_schemas_cache."""
        topo = {"processes": [{"process_name": "proc", "plugins": [{"plugin_name": "bare"}]}], "wires": []}
        p = _presenter(topo, plugin_specs={"bare": _spec("bare")})

        p._topology_to_graph(topo)

        assert p._port_schemas_cache == {}


# --------------------------------------------------------------------------- #
#  Wires: резолв endpoint → node_id                                            #
# --------------------------------------------------------------------------- #


class TestWireEndpoints:
    def test_endpoint_variants(self):
        """endpoint `proc.plugin.port`, без plugin-сегмента, на процесс без плагинов."""
        topo = {
            "processes": [
                {"process_name": "src", "plugins": [{"plugin_name": "cap"}]},
                {"process_name": "dst", "plugins": [{"plugin_name": "snk"}]},
                {"process_name": "bare", "plugins": []},
            ],
            "wires": [
                # полный endpoint proc.plugin.port
                {"source": "src.cap.frame", "target": "dst.snk.frame"},
                # без plugin-сегмента → первый плагин процесса
                {"source": "src", "target": "dst"},
                # источник — процесс без плагинов → node_id = process
                {"source": "bare", "target": "dst.snk.frame"},
            ],
        }
        p = _presenter(topo, plugin_specs={"cap": _spec("cap"), "snk": _spec("snk")})

        _nodes, edges = p._topology_to_graph(topo)

        wire_edges = [(e.source_id, e.target_id) for e in edges if not e.implicit]
        assert wire_edges == [
            ("src.cap", "dst.snk"),
            ("src.cap", "dst.snk"),
            ("bare", "dst.snk"),
        ]


# --------------------------------------------------------------------------- #
#  Displays: боксы и binding-рёбра                                             #
# --------------------------------------------------------------------------- #


class TestDisplays:
    def test_fan_in_single_box(self):
        """Два источника на один display_id → один бокс (fan-in), два binding-ребра."""
        topo = {
            "processes": [
                {"process_name": "a", "plugins": [{"plugin_name": "p1"}]},
                {"process_name": "b", "plugins": [{"plugin_name": "p2"}]},
            ],
            "wires": [],
            "displays": [
                {"node_id": "a.p1.frame", "display_id": "D1"},
                {"node_id": "b.p2.frame", "display_id": "D1"},
            ],
        }
        p = _presenter(topo, plugin_specs={"p1": _spec("p1"), "p2": _spec("p2")})

        _nodes, edges = p._topology_to_graph(topo)

        boxes = p._display_nodes_cache
        assert [b.display_id for b in boxes] == ["D1"]
        binding_edges = [(e.source_id, e.target_id) for e in edges if e.target_id == "D1"]
        assert binding_edges == [("a.p1", "D1"), ("b.p2", "D1")]

    def test_binding_without_display_id_skipped(self):
        """Binding без display_id пропускается (нет бокса, нет ребра)."""
        topo = {
            "processes": [{"process_name": "a", "plugins": [{"plugin_name": "p1"}]}],
            "wires": [],
            "displays": [{"node_id": "a.p1.frame", "display_id": ""}],
        }
        p = _presenter(topo, plugin_specs={"p1": _spec("p1")})

        _nodes, edges = p._topology_to_graph(topo)

        assert p._display_nodes_cache == []
        assert [e for e in edges if not e.implicit] == []

    def test_fallback_positions_increment(self):
        """Боксы без gui_positions встают в дефолт (600, 50 + i*120) с инкрементом."""
        topo = {
            "processes": [
                {"process_name": "a", "plugins": [{"plugin_name": "p1"}]},
                {"process_name": "b", "plugins": [{"plugin_name": "p2"}]},
            ],
            "wires": [],
            "displays": [
                {"node_id": "a.p1.frame", "display_id": "D1"},
                {"node_id": "b.p2.frame", "display_id": "D2"},
            ],
        }
        p = _presenter(topo, plugin_specs={"p1": _spec("p1"), "p2": _spec("p2")})

        p._topology_to_graph(topo)

        pos = {b.display_id: (b.x, b.y) for b in p._display_nodes_cache}
        assert pos["D1"] == (600.0, 50.0)
        assert pos["D2"] == (600.0, 170.0)

    def test_placed_but_unbound_and_dedup(self):
        """placed-but-unbound бокс дорисован; id и в topo, и в placed → дедуп (один бокс)."""
        topo = {
            "processes": [{"process_name": "a", "plugins": [{"plugin_name": "p1"}]}],
            "wires": [],
            "displays": [{"node_id": "a.p1.frame", "display_id": "D_bound"}],
        }
        p = _presenter(topo, plugin_specs={"p1": _spec("p1")})
        # D_bound есть и в topo, и среди размещённых (проверяем дедуп);
        # D_placed — только размещён, но не привязан (проверяем дорисовку).
        p._layout.placed_display_ids = {"D_bound", "D_placed"}

        _nodes, _edges = p._topology_to_graph(topo)

        ids = sorted(b.display_id for b in p._display_nodes_cache)
        assert ids == ["D_bound", "D_placed"]  # ровно по одному, без дублей


# --------------------------------------------------------------------------- #
#  Позиции узлов                                                                #
# --------------------------------------------------------------------------- #


class TestNodePositions:
    def test_priority_node_id_over_anchor(self):
        """Позиция node_id в gui_positions приоритетнее anchor'а процесса."""
        topo = {"processes": [{"process_name": "proc", "plugins": [{"plugin_name": "pl"}]}], "wires": []}
        p = _presenter(topo, plugin_specs={"pl": _spec("pl")})
        p._layout.gui_positions["proc"] = (100.0, 200.0)  # anchor
        p._layout.gui_positions["proc.pl"] = (11.0, 22.0)  # node_id — победитель

        nodes, _edges = p._topology_to_graph(topo)

        node = _by_id(nodes)["proc.pl"]
        assert (node.x, node.y) == (11.0, 22.0)

    def test_process_anchor_position(self):
        """Без позиции node_id плагин 0 встаёт в anchor процесса."""
        topo = {"processes": [{"process_name": "proc", "plugins": [{"plugin_name": "pl"}]}], "wires": []}
        p = _presenter(topo, plugin_specs={"pl": _spec("pl")})
        p._layout.gui_positions["proc"] = (100.0, 200.0)

        nodes, _edges = p._topology_to_graph(topo)

        node = _by_id(nodes)["proc.pl"]
        assert (node.x, node.y) == (100.0, 200.0)

    def test_default_cluster_position(self):
        """Без gui_positions — дефолтный кластер: колонка по индексу процесса."""
        topo = {"processes": [{"process_name": "proc", "plugins": [{"plugin_name": "pl"}]}], "wires": []}
        p = _presenter(topo, plugin_specs={"pl": _spec("pl")})

        nodes, _edges = p._topology_to_graph(topo)

        node = _by_id(nodes)["proc.pl"]
        # base_x = 60 + process_index(0) * 340 = 60; plugin_index 0 → без смещения.
        # base_y = 60 + HEADER(24) + PADDING(16) = 100.
        expected_x = 60.0 + 0 * (NODE_WIDTH + CONTAINER_INNER_GAP)  # plugin_index 0 → 0 смещения
        expected_y = 60.0 + CONTAINER_HEADER_H + CONTAINER_PADDING
        assert node.x == expected_x
        assert node.y == expected_y


# --------------------------------------------------------------------------- #
#  Lock                                                                         #
# --------------------------------------------------------------------------- #


class TestLock:
    def test_locked_plugin_node(self):
        """node_id в _locked_nodes → NodeData.locked=True."""
        topo = {"processes": [{"process_name": "proc", "plugins": [{"plugin_name": "pl"}]}], "wires": []}
        p = _presenter(topo, plugin_specs={"pl": _spec("pl")})
        p._layout.locked_nodes = {"proc.pl"}

        nodes, _edges = p._topology_to_graph(topo)

        assert _by_id(nodes)["proc.pl"].locked is True

    def test_locked_fallback_node(self):
        """Имя процесса без плагинов в _locked_nodes → fallback-нода locked=True."""
        topo = {"processes": [{"process_name": "empty", "plugins": []}], "wires": []}
        p = _presenter(topo)
        p._layout.locked_nodes = {"empty"}

        nodes, _edges = p._topology_to_graph(topo)

        assert _by_id(nodes)["empty"].locked is True


# --------------------------------------------------------------------------- #
#  Subtitle: ключевой параметр плагина                                         #
# --------------------------------------------------------------------------- #


class TestSubtitle:
    @pytest.mark.parametrize(
        "plugin_dict, expected",
        [
            ({"plugin_name": "color_convert", "mode": "rgb2gray"}, "processing · rgb2gray"),
            ({"plugin_name": "color_convert", "config": {"mode": "hsv"}}, "processing · hsv"),
            ({"plugin_name": "color_convert"}, "processing"),  # нет mode → просто категория
        ],
    )
    def test_color_convert_subtitle(self, plugin_dict, expected):
        """subtitle color_convert берёт `mode` из плоского и вложенного config."""
        topo = {"processes": [{"process_name": "proc", "plugins": [plugin_dict]}], "wires": []}
        p = _presenter(topo, plugin_specs={"color_convert": _spec("color_convert", category="processing")})

        nodes, _edges = p._topology_to_graph(topo)

        assert nodes[0].subtitle == expected


# --------------------------------------------------------------------------- #
#  Round-trip: сериализация рецепта graph→dict                                 #
# --------------------------------------------------------------------------- #


class TestRoundTrip:
    def test_graph_to_blueprint_preserves_topology(self):
        """Загрузка топологии в модель → graph_to_blueprint сохраняет процессы/wires/displays."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.io import graph_to_blueprint

        topo = {
            "processes": [
                {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
                {"process_name": "proc", "plugins": [{"plugin_name": "mask"}]},
            ],
            "wires": [{"source": "cam.capture.frame", "target": "proc.mask.frame"}],
            "displays": [{"node_id": "proc.mask.frame", "display_id": "D1"}],
        }
        p = _presenter(topo, plugin_specs={"capture": _spec("capture"), "mask": _spec("mask")})
        p.load_topology_from_config()

        bp_dict, bindings, _gui = graph_to_blueprint(p.model)

        names = [proc["process_name"] for proc in bp_dict["processes"]]
        assert names == ["cam", "proc"]
        # Текущее поведение: wire несёт пустое поле description (модель добавляет его
        # при round-trip). Фиксируем как есть — характеризация, не «улучшение».
        assert bp_dict["wires"] == [
            {"source": "cam.capture.frame", "target": "proc.mask.frame", "description": ""}
        ]
        assert bindings == [{"node_id": "proc.mask.frame", "display_id": "D1"}]
