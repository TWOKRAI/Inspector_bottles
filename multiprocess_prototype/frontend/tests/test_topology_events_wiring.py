# -*- coding: utf-8 -*-
"""Интеграционный тест topology-событий (Phase G G.3).

Проверяет ПОЛНУЮ production-цепочку на РЕАЛЬНЫХ компонентах (не Fake):
    store.set_topology(...) / save(...) → TopologyRepositoryStore публикует
        TopologyReplaced на реальный QtEventBus
        → PipelinePresenter scene reload (self-subscribe в __init__)
        → TopologyBridge cache invalidation (подписка из app.py composition root).

G.3: store сам публикует TopologyReplaced (publisher-мост topology_events удалён).
Триггер — реальный store.set_topology, как его зовут ActionBus handlers (recipe_apply,
topology mutation) и presenter.save().
"""

from __future__ import annotations

from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryStore
from multiprocess_prototype.domain.events import TopologyReplaced
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.qt_event_bus import QtEventBus
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter


def test_set_topology_triggers_presenter_reload(qtbot) -> None:
    """store.set_topology → QtEventBus publish → presenter обновляет модель."""
    events = QtEventBus()
    store = TopologyRepositoryStore({"processes": [], "wires": []}, events=events)
    services = make_test_app_services(topology=store, events=events)

    # Presenter подписывается на TopologyReplaced в __init__
    presenter = PipelinePresenter(services)
    presenter.load_topology_from_config()
    assert presenter.model.get_process_names() == []

    # Реальная мутация: ActionBus/recipe пишут именно так
    store.set_topology({"processes": [{"process_name": "live_proc", "plugins": []}], "wires": []})

    # Обновление пришло через typed EventBus (store сам опубликовал TopologyReplaced)
    assert "live_proc" in presenter.model.get_process_names()


def test_set_topology_invalidates_bridge_cache(qtbot) -> None:
    """store.set_topology → EventBus → bridge.on_topology_changed (как в app.py)."""
    events = QtEventBus()
    store = TopologyRepositoryStore({"processes": [], "wires": []}, events=events)
    calls: list[int] = []

    class _FakeBridge:
        def on_topology_changed(self) -> None:
            calls.append(1)

    bridge = _FakeBridge()
    # Обвязка из composition root (app.py блок 3h.1)
    events.subscribe(TopologyReplaced, lambda _e: bridge.on_topology_changed())

    store.set_topology({"processes": [{"process_name": "x", "plugins": []}], "wires": []})

    assert calls == [1]
