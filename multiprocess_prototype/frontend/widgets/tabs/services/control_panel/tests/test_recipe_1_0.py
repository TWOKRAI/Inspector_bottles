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
  А3. ``parse_controls`` на конфиге плагина процесса ``pult`` даёт среди контролов РОВНО ОДИН
      контрол ``word`` (после Task 6.4 в ``pult`` есть и другие: лента, мониторы):
      type text, source param, id word, label «Слово», target_process layout,
      target_plugin_index 0, target_field target_word.
  А4. Контрол из рецепта → реальный ``ControlPanelPresenter.operate(spec, "МИР")`` → реальный
      ``CommandDispatcherOrchestrator`` → ровно одно ``PluginConfigChanged`` (layout, 0,
      target_word, "МИР"); ``resolve_plugin_register(topology, "layout", 0) == "word_layout"``.
  А5. Слово, лента и мониторы процесса ``pult`` в двух рецептах идентичны; «Домой» и
      «Серво ВКЛ» только в sim (в β — после R4, Task 6.4).

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
def test_word_control_is_exactly_one(recipe: str) -> None:
    """А3 (обновлено в 6.4): контрол ``word`` ровно один (``parse_controls`` молча роняет битые записи).

    Было «ровно один контрол в pult»; с 6.4 рядом лента/мониторы, «слово первым» держит
    ``test_word_control_still_first``.
    """
    from Services.control_panel.controls import parse_controls

    raw = _pult_controls_raw(recipe)
    parsed = parse_controls(raw)
    # ничего не уронено молча: записей в рецепте столько же, сколько распарсилось
    assert len(raw) == len(parsed), f"parse_controls уронил записи: в рецепте {len(raw)}, распарсено {len(parsed)}"
    words = [c for c in parsed if c.id == "word"]
    assert len(words) == 1, f"ожидался ровно один контрол 'word', получено {[c.id for c in parsed]}"
    actual = {k: getattr(words[0], k) for k in _EXPECTED_WORD_CONTROL}
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


# --------------------------------------------------------------------------- #
# А5
# --------------------------------------------------------------------------- #


def test_pult_controls_identical_in_both_recipes() -> None:
    """А5 (обновлено в 6.4): слово, лента и мониторы ``pult`` в двух рецептах равны (список словарей).

    «Домой» и «Серво ВКЛ» (robot_park/robot_servo) есть только в sim — в β их нет до R4;
    их отсутствие в β пинит ``test_beta_has_no_home_servo_before_r4``.
    """
    sim, real = (_pult_controls_raw(name) for name in _RECIPE_NAMES)
    # страж против «пусто == пусто»: без контролов сравнение прошло бы вхолостую
    assert sim, "в letter_robot_sim у pult нет контролов"
    assert real, "в hikvision_letter_robot у pult нет контролов"
    home_servo = ("robot_park", "robot_servo")
    sim_common = [c for c in sim if c.get("target_command") not in home_servo]
    assert len(sim_common) == len(sim) - 2, "в sim нет «Домой»/«Серво ВКЛ»: сравнение общей части вхолостую"
    assert sim_common == real


# =========================================================================== #
# Task 6.4 «кнопки ленты, Домой, Серво ВКЛ, строка статуса» (слепой tester, до реализации)
#
# Критерии приёмки (источник — plans/pult-control-panel-phase6.md, Task 6.4, В1/В2/В8):
#   Б1. letter_robot_sim: у pult помимо «Слова» 4 action-контрола на хаб (devices/0, source action,
#       type button): «Лента пуск» vfd_run {device_id: vfd_belt}; «Лента стоп» vfd_stop {device_id: vfd_belt};
#       «Домой» robot_park {device_id: robot_main}; «Серво ВКЛ» robot_servo, value_arg on,
#       {device_id: robot_main}, отправляемое значение on = True.
#   Б2. 5 monitor-контролов (source monitor, type monitor) по state_path: devices.state.robot_main.conn
#       (value_key conn), devices.state.robot_main.park.state, processes.layout.state.word_layout.{last_label,
#       assembled, done}. Монитора system.run.state нет.
#   Б3. hikvision_letter_robot (β, протокол v1, R4 не влит): лента и 5 мониторов есть; «Домой» и «Серво ВКЛ»
#       ОТСУТСТВУЮТ (test_beta_has_no_home_servo_before_r4 — лид снимает при слиянии R4).
#   Б4. «Слово» остаётся первым контролом и не меняется.
#   Б5. Все 4 команды есть в DeviceHubPlugin.commands; РЕАЛЬНЫЙ CommandCatalog + CommandValidator
#       принимают validate_action_command("device_hub", <команда>).
#
# Ожидаемое — литералы. Контролы ищутся по label (action) и по state_path (monitor): id в приёмке не заданы.
# Сырые dict-контролы сравниваются как есть (parse_controls до Task 6.3 молча роняет monitor).
# =========================================================================== #

_BELT_ACTIONS = [
    ("Лента пуск", "vfd_run", {"device_id": "vfd_belt"}, ""),
    ("Лента стоп", "vfd_stop", {"device_id": "vfd_belt"}, ""),
]
_HOME_SERVO_ACTIONS = [
    ("Домой", "robot_park", {"device_id": "robot_main"}, ""),
    ("Серво ВКЛ", "robot_servo", {"device_id": "robot_main"}, "on"),
]
_ALL_ACTIONS = _BELT_ACTIONS + _HOME_SERVO_ACTIONS

_MONITOR_PATHS = [
    "devices.state.robot_main.conn",
    "devices.state.robot_main.park.state",
    "processes.layout.state.word_layout.last_label",
    "processes.layout.state.word_layout.assembled",
    "processes.layout.state.word_layout.done",
]

_SIM = "letter_robot_sim"
_BETA = "hikvision_letter_robot"


def _actions_by_label(recipe: str) -> dict[str, dict[str, Any]]:
    """Сырые action-контролы pult по label (дубль label — отказ теста с понятным текстом)."""
    out: dict[str, dict[str, Any]] = {}
    for c in _pult_controls_raw(recipe):
        if c.get("source") == "action":
            label = c.get("label")
            assert label not in out, f"два action-контрола с label {label!r} в {recipe}"
            out[label] = c
    return out


def _monitors(recipe: str) -> list[dict[str, Any]]:
    return [c for c in _pult_controls_raw(recipe) if c.get("source") == "monitor"]


def _assert_action_spec(c: dict[str, Any], command: str, args: dict[str, Any], value_arg: str) -> None:
    assert c.get("type") == "button", c
    assert c.get("source") == "action", c
    assert c.get("target_process") == "devices", c
    assert c.get("target_plugin_index") == 0, c
    assert c.get("target_command") == command, c
    assert c.get("command_args") == args, c
    assert (c.get("value_arg") or "") == value_arg, c


@pytest.fixture(scope="module")
def _hub_registry() -> Any:
    """PluginRegistry с найденными плагинами (как в GUI/загрузчике); страж «ноль наблюдений»."""
    from multiprocess_framework.modules.app_module import discover
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    discover(plugin_paths=[str(_PROJECT_ROOT / "Plugins"), str(_PROJECT_ROOT / "Services")], service_paths=[])
    assert PluginRegistry.get("device_hub") is not None, "реестр не знает device_hub: валидатор ничего бы не проверил"
    return PluginRegistry


def test_belt_home_servo_commands_exist(_hub_registry: Any) -> None:
    """Б1+Б5: в рецепте sim есть 4 кнопки с нужными командами и аргументами; команды есть у DeviceHubPlugin."""
    from Plugins.hub.device_hub.plugin import DeviceHubPlugin

    actions = _actions_by_label(_SIM)
    assert sorted(actions) == sorted(label for label, *_ in _ALL_ACTIONS), (
        f"в pult нет ровно 4 action-контролов «Лента пуск/стоп», «Домой», «Серво ВКЛ»: {sorted(actions)}"
    )
    for label, command, args, value_arg in _ALL_ACTIONS:
        _assert_action_spec(actions[label], command, args, value_arg)
        assert command in DeviceHubPlugin.commands, f"{command} нет в DeviceHubPlugin.commands"


def test_servo_on_sends_on_true_args() -> None:
    """Б1: «Серво ВКЛ» после parse_controls шлёт {device_id: robot_main, on: True}; остальные — только command_args."""
    from Services.control_panel.controls import parse_controls

    actions = _actions_by_label(_SIM)
    assert "Серво ВКЛ" in actions, "нет контрола «Серво ВКЛ»"
    by_label = {s.label: s for s in parse_controls(list(actions.values()))}
    assert set(by_label) == {label for label, *_ in _ALL_ACTIONS}, "parse_controls уронил action-контролы"
    assert by_label["Серво ВКЛ"].action_args(None) == {"device_id": "robot_main", "on": True}
    assert by_label["Домой"].action_args(None) == {"device_id": "robot_main"}
    assert by_label["Лента пуск"].action_args(None) == {"device_id": "vfd_belt"}
    assert by_label["Лента стоп"].action_args(None) == {"device_id": "vfd_belt"}


def test_status_monitors_paths() -> None:
    """Б2: в sim ровно 5 monitor-контролов с нужными state_path; conn несёт value_key conn."""
    mons = _monitors(_SIM)
    assert sorted(str(m.get("state_path")) for m in mons) == sorted(_MONITOR_PATHS), (
        f"monitor-контролы pult: {[m.get('state_path') for m in mons]}"
    )
    conn = next(m for m in mons if m.get("state_path") == "devices.state.robot_main.conn")
    assert conn.get("value_key") == "conn"


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_monitors_have_type_monitor(recipe: str) -> None:
    """Б2: тип monitor-контролов — ``monitor`` (так в приёмке; зависит от решения Task 6.3 о ControlType)."""
    mons = _monitors(recipe)
    assert len(mons) == 5, f"ожидалось 5 monitor-контролов, найдено {len(mons)}"
    assert [m.get("type") for m in mons] == ["monitor"] * 5


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_monitors_survive_parse_controls(recipe: str) -> None:
    """Б2: ``parse_controls`` (до 6.3 роняет type monitor / не знает state_path) сохраняет 5 мониторов с полями."""
    from Services.control_panel.controls import parse_controls

    raw = _pult_controls_raw(recipe)
    parsed = parse_controls(raw)
    assert len(parsed) == len(raw), (
        f"parse_controls уронил записи: рецепт {len(raw)}, распарсено {len(parsed)} (monitor/state_path не поддержан?)"
    )
    mons = [s for s in parsed if s.source == "monitor"]
    assert sorted(getattr(s, "state_path", "") for s in mons) == sorted(_MONITOR_PATHS), (
        "ControlSpec не хранит state_path или мониторов нет"
    )
    conn = next(s for s in mons if getattr(s, "state_path", "") == "devices.state.robot_main.conn")
    assert getattr(conn, "value_key", "") == "conn"


def test_sim_recipe_has_four_actions_and_five_monitors() -> None:
    """Б1+Б2+Б4: pult в sim = «Слово» + ровно 4 action + ровно 5 monitor, ничего лишнего."""
    raw = _pult_controls_raw(_SIM)
    assert [c.get("source") for c in raw].count("action") == 4
    assert [c.get("source") for c in raw].count("monitor") == 5
    labels = [c.get("label") for c in raw]
    assert len(raw) == 10, f"ожидалось 10 контролов (слово + 4 + 5), найдено {len(raw)}: {labels}"
    assert raw[0].get("id") == "word"


def test_beta_has_belt_and_monitors() -> None:
    """Б3: в β есть «Лента пуск/стоп» (те же аргументы) и те же 5 мониторов; слово первым."""
    actions = _actions_by_label(_BETA)
    for label, command, args, value_arg in _BELT_ACTIONS:
        assert label in actions, f"в β нет контрола {label!r}: {sorted(actions)}"
        _assert_action_spec(actions[label], command, args, value_arg)
    assert sorted(str(m.get("state_path")) for m in _monitors(_BETA)) == sorted(_MONITOR_PATHS)
    assert _pult_controls_raw(_BETA)[0].get("id") == "word"


def test_beta_has_no_home_servo_before_r4() -> None:
    """Б3: пока R4 не влит (протокол v1), в β НЕТ «Домой» и «Серво ВКЛ». Лид снимает тест при слиянии R4.

    Страж против пустоты: лента в β уже есть (иначе «нет Домой» верно вхолостую).
    """
    raw = _pult_controls_raw(_BETA)
    assert len(raw) == 8, f"β: ожидалось 8 контролов (слово + лента 2 + 5 мониторов), найдено {len(raw)}"
    assert {c.get("label") for c in raw} >= {"Лента пуск", "Лента стоп"}, "ленты в β ещё нет: проверка пуста"
    assert not [c for c in raw if c.get("target_command") in ("robot_park", "robot_servo")]
    assert not [c for c in raw if c.get("label") in ("Домой", "Серво ВКЛ")]


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_word_control_still_first(recipe: str) -> None:
    """Б4: «Слово» — первый контрол pult и совпадает с исходным дословно (регрессионный страж, не RED)."""
    raw = _pult_controls_raw(recipe)
    assert raw, f"у pult в {recipe} нет контролов"
    assert raw[0] == {**_EXPECTED_WORD_CONTROL}, raw[0]


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_no_system_run_state_monitor(recipe: str) -> None:
    """Б2: монитора ``system.run.state`` нет (статус системы показывает RunControlWidget главного окна)."""
    mons = _monitors(recipe)
    assert len(mons) == 5, "мониторов ещё нет: проверка «нет system.run.state» была бы пустой"
    for c in _pult_controls_raw(recipe):
        for key in ("state_path", "target_field", "target_command"):
            assert "system.run" not in str(c.get(key, "")), c


@pytest.mark.parametrize(
    ("recipe", "expected"),
    [(_SIM, _ALL_ACTIONS), (_BETA, _BELT_ACTIONS)],
)
def test_gui_validator_accepts_belt_and_home(recipe: str, expected: list, _hub_registry: Any) -> None:
    """Б5: рецепт → parse_controls → РЕАЛЬНЫЙ CommandCatalog + CommandValidator принимают команды action-контролов.

    plugin_name берётся из топологии рецепта по (target_process, target_plugin_index), как делает GUI.
    """
    from multiprocess_framework.modules.registers_module.core.manager import RegistersManager
    from multiprocess_prototype.frontend.bridge.command_catalog import CommandCatalog
    from multiprocess_prototype.frontend.bridge.command_validator import CommandValidator
    from multiprocess_prototype.registers.connection_map import ConnectionMap
    from Services.control_panel.controls import parse_controls

    topo = _topology_dict(recipe)
    catalog = CommandCatalog.from_registry_and_map(_hub_registry, ConnectionMap.from_topology(topo))
    validator = CommandValidator(catalog, RegistersManager.from_registry(_hub_registry))

    specs = [s for s in parse_controls(_pult_controls_raw(recipe)) if s.source == "action"]
    assert sorted(s.target_command for s in specs) == sorted(cmd for _, cmd, _, _ in expected), (
        f"action-контролы в {recipe}: {[s.target_command for s in specs]}"
    )
    procs = {p["process_name"]: p for p in topo["processes"]}
    for s in specs:
        plugin_name = procs[s.target_process]["plugins"][s.target_plugin_index]["plugin_name"]
        assert plugin_name == "device_hub"
        res = validator.validate_action_command(plugin_name, s.target_command)
        assert res.ok is True, f"{s.target_command}: {res.error}"
    # валидатор не заглушка: несуществующую команду отвергает
    assert validator.validate_action_command("device_hub", "no_such_command").ok is False
