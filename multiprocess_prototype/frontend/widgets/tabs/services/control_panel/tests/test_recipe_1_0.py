# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 6.1 «поле Слово в рецептах 1.0» (слепой tester, до реализации).

Цель: во вкладке Services → «Пульт» оператор вводит слово, и оно без перезапуска уходит в
регистр ``target_word`` плагина ``word_layout`` процесса ``layout``.

Критерии приёмки (единственный источник требований):
  А1. В ОБОИХ рецептах (letter_robot_sim, hikvision_letter_robot) последним процессом стоит
      ``pult`` с плагином ControlPanelPlugin (категория source).
  А2. Оба рецепта проходят ``SystemBlueprint.check() == []`` тем же путём, что и загрузчик
      (``load_topology_dict`` → ``normalize_blueprint`` → ``model_validate`` →
      ``infer_missing_collectors`` → ``check``), а не облегчённым ``validate_recipe_blueprint``.
  А3. ``parse_controls`` на конфиге плагина процесса ``pult`` даёт РОВНО ОДИН контрол:
      type text, source param, id word, label «Слово», target_process layout,
      target_plugin_index 0, target_field target_word.
  А4. Контрол из рецепта → реальный ``ControlPanelPresenter.operate(spec, "МИР")`` → реальный
      ``CommandDispatcherOrchestrator`` → ровно одно ``PluginConfigChanged`` (layout, 0,
      target_word, "МИР"); ``resolve_plugin_register(topology, "layout", 0) == "word_layout"``.
  А5. Набор контролов процесса ``pult`` в двух рецептах идентичен.

Ожидаемые значения — литералы, не вычисляются из кода под тестом. Если процесса ``pult`` в
рецепте нет, тесты падают AssertionError с текстом «процесса pult нет», а не ошибкой теста.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[7]
_RECIPES_DIR = _PROJECT_ROOT / "multiprocess_prototype" / "recipes"
_RECIPE_NAMES = ["letter_robot_sim", "hikvision_letter_robot"]

# Ожидаемый единственный контрол — литералом (критерий А3).
_EXPECTED_WORD_CONTROL = {
    "id": "word",
    "type": "text",
    "source": "param",
    "label": "Слово",
    "target_process": "layout",
    "target_plugin_index": 0,
    "target_field": "target_word",
}

_CONTROL_PANEL_CLASS = "ControlPanelPlugin"


def _recipe_path(name: str) -> Path:
    return _RECIPES_DIR / f"{name}.yaml"


def _topology_dict(name: str) -> dict[str, Any]:
    """Плоская топология рецепта — так её читает загрузчик (``load_topology_dict``)."""
    from multiprocess_prototype.backend.launch import load_topology_dict

    return load_topology_dict(_recipe_path(name))


def _domain_topology_dict(name: str) -> dict[str, Any]:
    """Топология в виде, в котором её держит GUI (domain ``Topology``; конфиг плагина = ``config``)."""
    from multiprocess_prototype.domain.entities.topology import Topology

    return Topology.from_dict(_topology_dict(name)).to_dict()


def _pult_process(topology: dict[str, Any]) -> dict[str, Any]:
    procs = [p for p in topology["processes"] if p.get("process_name") == "pult"]
    assert len(procs) == 1, f"процесса pult нет (или он не один): найдено {len(procs)}"
    return procs[0]


def _pult_controls_raw(name: str) -> list[dict[str, Any]]:
    """Сырой список контролов из конфига ControlPanelPlugin процесса pult (в виде домена GUI)."""
    proc = _pult_process(_domain_topology_dict(name))
    plugins = [pl for pl in proc["plugins"] if str(pl.get("plugin_class", "")).endswith(_CONTROL_PANEL_CLASS)]
    assert len(plugins) == 1, f"в процессе pult нет ровно одного {_CONTROL_PANEL_CLASS}: {len(plugins)}"
    return list(plugins[0]["config"].get("controls") or [])


# --------------------------------------------------------------------------- #
# А1
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_pult_node_last_in_both_recipes(recipe: str) -> None:
    """А1: processes[-1] — это ``pult`` с ControlPanelPlugin категории source."""
    procs = _topology_dict(recipe)["processes"]
    names = [p.get("process_name") for p in procs]
    assert names[-1] == "pult", (
        f"последний процесс — {names[-1]!r}, ожидался 'pult' (процесса pult нет?); порядок: {names}"
    )
    plugins = procs[-1].get("plugins") or []
    cp = [pl for pl in plugins if str(pl.get("plugin_class", "")).endswith(_CONTROL_PANEL_CLASS)]
    assert len(cp) == 1, f"в pult нет ровно одного {_CONTROL_PANEL_CLASS}: {[pl.get('plugin_class') for pl in plugins]}"
    assert cp[0].get("category") == "source"


# --------------------------------------------------------------------------- #
# А2
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_recipes_pass_blueprint_check(recipe: str) -> None:
    """А2: ``SystemBlueprint.check() == []`` тем же путём, что и загрузчик (не облегчённой проверкой)."""
    from multiprocess_framework.modules.app_module import discover
    from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
    from multiprocess_prototype.backend.config.schemas import load_system_config

    discover(plugin_paths=[str(_PROJECT_ROOT / "Plugins"), str(_PROJECT_ROOT / "Services")], service_paths=[])
    # страж «ноль наблюдений»: с пустым реестром check() молча пропускает плагины и вернёт []
    for plugin in ("word_layout", "control_panel"):
        assert PluginRegistry.get(plugin) is not None, f"реестр не знает {plugin}: check() ничего бы не проверил"

    bp_dict = normalize_blueprint(_topology_dict(recipe), load_system_config())
    topology = SystemBlueprint.model_validate(bp_dict)
    topology.infer_missing_collectors()
    errors = topology.check()
    assert errors == [], "check() загрузчика отклонил рецепт:\n  " + "\n  ".join(errors)


# --------------------------------------------------------------------------- #
# А3
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_word_control_is_the_only_control(recipe: str) -> None:
    """А3: ровно один контрол ``word`` (``parse_controls`` молча роняет битые записи)."""
    from Services.control_panel.controls import parse_controls

    raw = _pult_controls_raw(recipe)
    parsed = parse_controls(raw)
    # ничего не уронено молча: записей в рецепте столько же, сколько распарсилось
    assert len(raw) == len(parsed), f"parse_controls уронил записи: в рецепте {len(raw)}, распарсено {len(parsed)}"
    assert [c.id for c in parsed] == ["word"], f"ожидался ровно один контрол 'word', получено {[c.id for c in parsed]}"
    actual = {k: getattr(parsed[0], k) for k in _EXPECTED_WORD_CONTROL}
    assert actual == _EXPECTED_WORD_CONTROL


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
    assert [s["id"] for s in specs] == ["word"], f"в рецепте нет контрола word: {[s['id'] for s in specs]}"
    spec = specs[0]

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


# --------------------------------------------------------------------------- #
# А5
# --------------------------------------------------------------------------- #


def test_pult_controls_identical_in_both_recipes() -> None:
    """А5: наборы контролов ``pult`` в двух рецептах равны (список словарей)."""
    sim, real = (_pult_controls_raw(name) for name in _RECIPE_NAMES)
    # страж против «пусто == пусто»: без контролов сравнение прошло бы вхолостую
    assert sim, "в letter_robot_sim у pult нет контролов"
    assert real, "в hikvision_letter_robot у pult нет контролов"
    assert sim == real
