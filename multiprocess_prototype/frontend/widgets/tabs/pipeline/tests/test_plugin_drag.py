# -*- coding: utf-8 -*-
"""Тесты D.3: drag плагина между контейнерами + reorder + удаление плагин-ноды.

Покрытие (presenter + реальный orchestrator):
  - on_plugin_dropped cross-process → MovePlugin (плагин уходит в другой процесс);
  - on_plugin_dropped reorder внутри процесса → меняется порядок цепочки;
  - on_plugin_dropped no-op (та же позиция / вне контейнеров) → топология не меняется;
  - remove_selected(плагин-нода) в процессе с >1 плагином → RemovePlugin (только плагин);
  - remove_selected(плагин-нода) в процессе с 1 плагином → RemoveProcess (процесс).

Refs: plans/pipeline-process-container-nodes.md (Phase D.3)
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services_with_orchestrator


def _plugins(topo: dict, process: str) -> list[str]:
    """Имена плагинов процесса по порядку."""
    proc = next(p for p in topo["processes"] if p["process_name"] == process)
    return [pl["plugin_name"] for pl in proc.get("plugins", [])]


def _process_names(topo: dict) -> list[str]:
    return [p["process_name"] for p in topo["processes"]]


def _chain_two_processes():
    """preproc[resize, grayscale] + detector[yolo]."""
    topo = {
        "processes": [
            {
                "process_name": "preproc",
                "plugins": [{"plugin_name": "resize"}, {"plugin_name": "grayscale"}],
            },
            {"process_name": "detector", "plugins": [{"plugin_name": "yolo"}]},
        ],
        "wires": [],
    }
    return make_pipeline_services_with_orchestrator(topology=topo)


class TestDragCrossProcess:
    def test_move_plugin_to_other_process(self):
        """drag grayscale из preproc в detector → MovePlugin (cross-process)."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.on_plugin_dropped("preproc.grayscale", "preproc", 1, "detector", 1)

        topo = services.topology.load().to_dict()
        assert _plugins(topo, "preproc") == ["resize"]
        assert _plugins(topo, "detector") == ["yolo", "grayscale"]


class TestReorderWithinProcess:
    def test_reorder_moves_plugin(self):
        """drag grayscale (index 1) на позицию 0 внутри preproc → [grayscale, resize]."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.on_plugin_dropped("preproc.grayscale", "preproc", 1, "preproc", 0)

        topo = services.topology.load().to_dict()
        assert _plugins(topo, "preproc") == ["grayscale", "resize"]


class TestNoOpDrops:
    def test_same_position_no_change(self):
        """Дроп без смены позиции → топология не меняется."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.on_plugin_dropped("preproc.resize", "preproc", 0, "preproc", 0)

        topo = services.topology.load().to_dict()
        assert _plugins(topo, "preproc") == ["resize", "grayscale"]

    def test_drop_outside_containers_no_change(self):
        """Дроп вне контейнеров (to_process="") → топология не меняется."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.on_plugin_dropped("preproc.grayscale", "preproc", 1, "", -1)

        topo = services.topology.load().to_dict()
        assert _plugins(topo, "preproc") == ["resize", "grayscale"]
        assert _plugins(topo, "detector") == ["yolo"]


class TestDeletePluginNode:
    def test_remove_one_plugin_keeps_process(self):
        """remove_selected(плагин-нода) в процессе с >1 плагином → RemovePlugin."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["preproc.grayscale"])

        topo = services.topology.load().to_dict()
        assert "preproc" in _process_names(topo)  # процесс остался
        assert _plugins(topo, "preproc") == ["resize"]  # удалён только grayscale

    def test_remove_last_plugin_removes_process(self):
        """remove_selected(плагин-нода) в процессе с 1 плагином → RemoveProcess."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["detector.yolo"])

        topo = services.topology.load().to_dict()
        assert "detector" not in _process_names(topo)  # процесс удалён целиком

    def test_remove_by_process_name_legacy(self):
        """Legacy: remove_selected(имя процесса без точки) → RemoveProcess."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["preproc"])

        topo = services.topology.load().to_dict()
        assert "preproc" not in _process_names(topo)
