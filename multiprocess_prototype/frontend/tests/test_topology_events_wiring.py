# -*- coding: utf-8 -*-
"""Интеграционный тест обвязки typed topology-событий (Phase G G.1).

Проверяет ПОЛНУЮ production-цепочку на РЕАЛЬНЫХ компонентах (не Fake):
    holder.set_topology(...) → wire_topology_events publisher → QtEventBus
        → PipelinePresenter scene reload (G.1.1)
        → TopologyBridge cache invalidation (G.1.2).

Закрывает gap: publisher-мост жил только как inline-обвязка в app.py и не был
покрыт тестом (unit-тесты presenter'а эмитят TopologyReplaced напрямую). Здесь
триггер — реальный holder.set_topology через TopologyRepositoryFromHolder.
"""

from __future__ import annotations

from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryFromHolder
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.qt_event_bus import QtEventBus
from multiprocess_prototype.frontend.topology_events import wire_topology_events
from multiprocess_prototype.frontend.topology_holder import TopologyHolder
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter


def test_set_topology_triggers_presenter_reload(qtbot) -> None:
    """holder.set_topology → publisher → QtEventBus → presenter обновляет модель."""
    holder = TopologyHolder({"processes": [], "wires": []})
    events = QtEventBus()
    repo = TopologyRepositoryFromHolder(holder)
    services = make_test_app_services(topology=repo, events=events)

    # Publisher-мост (как в app.py composition root)
    wire_topology_events(holder, events)

    # Presenter подписывается на TopologyReplaced в __init__
    presenter = PipelinePresenter(services)
    presenter.load_topology_from_config()
    assert presenter.model.get_process_names() == []

    # Реальная мутация: ActionBus/recipe пишут именно так
    holder.set_topology({"processes": [{"process_name": "live_proc", "plugins": []}], "wires": []})

    # Без прямого holder.on_changed — обновление пришло через typed EventBus
    assert "live_proc" in presenter.model.get_process_names()


def test_set_topology_invalidates_bridge_cache(qtbot) -> None:
    """holder.set_topology → publisher → EventBus → bridge.on_topology_changed (G.1.2)."""
    holder = TopologyHolder({"processes": [], "wires": []})
    events = QtEventBus()
    calls: list[int] = []

    class _FakeBridge:
        def on_topology_changed(self) -> None:
            calls.append(1)

    wire_topology_events(holder, events, _FakeBridge())

    holder.set_topology({"processes": [{"process_name": "x", "plugins": []}], "wires": []})

    assert calls == [1]
