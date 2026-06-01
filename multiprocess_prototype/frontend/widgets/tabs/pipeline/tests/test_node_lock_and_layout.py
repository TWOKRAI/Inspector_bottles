"""Тесты фиксации нод + сохранения позиций при reload + skip locked в авто-раскладке.

Поведение по запросу владельца:
- ноду можно зафиксировать (не двигается drag'ом, ItemIsMovable=False);
- при мутации/reload ручные позиции не сбрасываются (sync из scene);
- авто-раскладка («Раскладка») не трогает зафиксированные ноды.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGraphicsItem

from multiprocess_prototype.domain.events import TopologyReplaced
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services


def _presenter_with_scene():
    """Презентер + scene, загруженные дефолтной топологией (camera.capture, processor.color_mask)."""
    services = make_pipeline_services()
    scene = GraphScene()
    p = PipelinePresenter(services)
    p.set_scene(scene)
    nodes, edges = p.load_topology_from_config()
    p.load_scene_with_ports(nodes, edges)
    return p, scene


def _is_movable(item) -> bool:
    return bool(item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)


def test_toggle_lock_sets_state_and_disables_move(qtbot):
    p, scene = _presenter_with_scene()
    node = scene.get_node("camera.capture")
    assert _is_movable(node) is True

    p.toggle_node_lock("camera.capture")
    assert "camera.capture" in p._locked_nodes
    assert node.locked is True
    assert _is_movable(node) is False

    # повторный вызов — освобождает
    p.toggle_node_lock("camera.capture")
    assert "camera.capture" not in p._locked_nodes
    assert node.locked is False
    assert _is_movable(node) is True


def test_lock_survives_topology_rebuild(qtbot):
    p, _scene = _presenter_with_scene()
    p.toggle_node_lock("camera.capture")
    # повторная сборка графа (как при reload из мутации)
    nodes, _edges = p._topology_to_graph(p._services.topology.load().to_dict())
    locked = {n.node_id: n.locked for n in nodes}
    assert locked["camera.capture"] is True
    assert locked["processor.color_mask"] is False


def test_auto_layout_skips_locked(qtbot):
    p, scene = _presenter_with_scene()
    node = scene.get_node("camera.capture")
    node.setPos(999.0, 888.0)
    p.toggle_node_lock("camera.capture")  # фиксируем на этой позиции

    p.auto_layout_scene()

    # зафиксированная нода осталась на месте
    assert (node.pos().x(), node.pos().y()) == (999.0, 888.0)
    # незафиксированная — переразложена (не в 999/888)
    other = scene.get_node("processor.color_mask")
    assert (other.pos().x(), other.pos().y()) != (999.0, 888.0)


def test_reload_preserves_manual_position(qtbot):
    p, scene = _presenter_with_scene()
    node = scene.get_node("processor.color_mask")
    node.setPos(500.0, 600.0)  # «перетащили» вручную

    # любая мутация → _on_topology_replaced пересобирает scene
    p._on_topology_replaced(TopologyReplaced(reason="test"))

    node2 = scene.get_node("processor.color_mask")
    assert (round(node2.pos().x()), round(node2.pos().y())) == (500, 600)
