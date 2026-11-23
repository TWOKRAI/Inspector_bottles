# -*- coding: utf-8 -*-
"""Приёмочный тест А4 Task 6.1: контрол «Слово» из рецепта доходит до регистра `target_word` через реальные Presenter и
Dispatcher. Критерии А1–А5 — в докстринге `test_recipe_1_0.py`; общие помощники — `recipe_pult_support.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.tests.recipe_pult_support import (
    _RECIPE_NAMES,
    _domain_topology_dict,
    _pult_controls_raw,
)


# --------------------------------------------------------------------------- #
# А4
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_word_control_writes_target_word(recipe: str) -> None:
    """А4: контрол рецепта → реальные Presenter и Dispatcher → PluginConfigChanged(layout, 0, target_word, "МИР").

    Реальные объекты: parse_controls, ControlPanelPresenter, CommandDispatcherOrchestrator,
    ProjectHolder, TopologyRepositoryStore, EventBus, Project.apply. Заглушка только одна:
    ``services`` — пространство имён с ``commands`` и ``topology`` (AppServices целиком — Qt).
    """
    from multiprocess_framework.modules.frontend_module.bridge.plugin_register_resolver import (
        resolve_plugin_register,
    )
    from multiprocess_prototype.adapters.dispatch.command_dispatcher import (
        CommandDispatcherOrchestrator,
        ProjectHolder,
    )
    from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryStore
    from multiprocess_prototype.domain.entities.project import ApplyContext, Project
    from multiprocess_prototype.domain.entities.topology import Topology
    from multiprocess_prototype.domain.event_bus import EventBus
    from multiprocess_prototype.domain.events import PluginConfigChanged
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.presenter import (
        ControlPanelPresenter,
    )
    from Services.control_panel.controls import controls_to_dicts, parse_controls

    topo_dict = _domain_topology_dict(recipe)

    # Контрол берём из рецепта в том виде, в каком пульт получает его от плагина (controls_to_dicts).
    specs = controls_to_dicts(parse_controls(_pult_controls_raw(recipe)))
    words = [s for s in specs if s["id"] == "word"]  # с 6.4 рядом лента/мониторы: ищем по id, не specs[0]
    assert len(words) == 1, f"в рецепте нет ровно одного контрола word: {[s['id'] for s in specs]}"
    spec = words[0]

    # Реальный стек GUI-диспетчера на топологии рецепта.
    bus = EventBus()
    events: list[PluginConfigChanged] = []
    bus.subscribe(PluginConfigChanged, events.append)
    holder = ProjectHolder(initial=Project(topology=Topology.from_dict(topo_dict)))
    store = TopologyRepositoryStore(topo_dict, events=bus)
    dispatcher = CommandDispatcherOrchestrator(
        project_holder=holder,
        topology_repo=store,
        event_bus=bus,
        apply_context_factory=ApplyContext,
    )
    presenter = ControlPanelPresenter(bridge=None, services=SimpleNamespace(commands=dispatcher, topology=store))

    ok = presenter.operate(spec, "МИР")

    assert ok is True
    assert len(events) == 1, f"ожидалось ровно одно PluginConfigChanged, получено {len(events)}: {events}"
    ev = events[0]
    assert (ev.process_name, ev.plugin_index, ev.field, ev.value) == ("layout", 0, "target_word", "МИР")

    # Наблюдаемый эффект в состоянии проекта: слово лежит в конфиге плагина layout[0].
    layout = holder.get().topology.find_process("layout")
    assert layout is not None
    assert layout.plugins[0].config["target_word"] == "МИР"

    # Адрес плагина → регистр word_layout (по нему live field-write уходит в живой процесс).
    assert resolve_plugin_register(topo_dict, "layout", 0) == "word_layout"
