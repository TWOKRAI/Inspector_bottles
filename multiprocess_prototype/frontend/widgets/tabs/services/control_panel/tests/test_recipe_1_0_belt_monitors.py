# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 6.4 «кнопки ленты, Домой, Серво ВКЛ, строка статуса» (блок Б1–Б5 из `test_recipe_1_0.py`).

Критерии А1–А5 Task 6.1 — в докстринге `test_recipe_1_0.py`; общие помощники — `recipe_pult_support.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.tests.recipe_pult_support import (
    _EXPECTED_WORD_CONTROL,
    _PROJECT_ROOT,
    _RECIPE_NAMES,
    _pult_controls_raw,
    _topology_dict,
)


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
#   Б3. hikvision_letter_robot (β, драйвер delta_v2 с R4): лента и 5 мониторов есть; «Домой» и «Серво ВКЛ» есть
#       с теми же аргументами, что в sim (Task 6.7; тест test_pult_controls_identical_in_both_recipes).
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
# Число-контрол скорости ленты (vfd_set_freq): тип number, а не button; пределы и стартовое значение — литералы рецепта.
_FREQ_LABEL = "Скорость ленты (Гц)"
_FREQ_ACTION = (_FREQ_LABEL, "vfd_set_freq", {"device_id": "vfd_belt"}, "freq_hz")
_HOME_SERVO_ACTIONS = [
    ("Домой", "robot_park", {"device_id": "robot_main"}, ""),
    ("Серво ВКЛ", "robot_servo", {"device_id": "robot_main"}, "on"),
]
_ALL_ACTIONS = [*_BELT_ACTIONS, _FREQ_ACTION, *_HOME_SERVO_ACTIONS]

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


def _assert_action_spec(
    c: dict[str, Any], command: str, args: dict[str, Any], value_arg: str, control_type: str = "button"
) -> None:
    assert c.get("type") == control_type, c
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
    """Б1+Б5: в sim 5 action-контролов с нужными командами и аргументами; команды есть у DeviceHubPlugin."""
    from Plugins.hub.device_hub.plugin import DeviceHubPlugin

    actions = _actions_by_label(_SIM)
    assert sorted(actions) == sorted(label for label, *_ in _ALL_ACTIONS), (
        f"в pult нет ровно 5 action-контролов (лента пуск/стоп, скорость, домой, серво ВКЛ): {sorted(actions)}"
    )
    for label, command, args, value_arg in _ALL_ACTIONS:
        _assert_action_spec(actions[label], command, args, value_arg, "number" if label == _FREQ_LABEL else "button")
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
    assert by_label[_FREQ_LABEL].action_args(25.0) == {"device_id": "vfd_belt", "freq_hz": 25.0}


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


def test_sim_recipe_has_five_actions_and_five_monitors() -> None:
    """Б1+Б2+Б4: pult в sim = «Слово» + ровно 5 action + ровно 5 monitor, ничего лишнего."""
    raw = _pult_controls_raw(_SIM)
    assert [c.get("source") for c in raw].count("action") == 5
    assert [c.get("source") for c in raw].count("monitor") == 5
    labels = [c.get("label") for c in raw]
    assert len(raw) == 11, f"ожидалось 11 контролов (слово + 5 + 5), найдено {len(raw)}: {labels}"
    assert raw[0].get("id") == "word"


@pytest.mark.parametrize("recipe", _RECIPE_NAMES)
def test_belt_freq_control_literals(recipe: str) -> None:
    """Контрол скорости ленты: number, vfd_set_freq на vfd_belt, value_arg freq_hz, 1..50 Гц, старт 10 Гц."""
    c = _actions_by_label(recipe)[_FREQ_LABEL]
    _assert_action_spec(c, "vfd_set_freq", {"device_id": "vfd_belt"}, "freq_hz", "number")
    assert (c.get("min"), c.get("max"), c.get("value")) == (1.0, 50.0, 10.0), c


def test_beta_has_belt_and_monitors() -> None:
    """Б3: в β есть «Лента пуск/стоп» (те же аргументы) и те же 5 мониторов; слово первым."""
    actions = _actions_by_label(_BETA)
    for label, command, args, value_arg in _BELT_ACTIONS:
        assert label in actions, f"в β нет контрола {label!r}: {sorted(actions)}"
        _assert_action_spec(actions[label], command, args, value_arg)
    assert sorted(str(m.get("state_path")) for m in _monitors(_BETA)) == sorted(_MONITOR_PATHS)
    assert _pult_controls_raw(_BETA)[0].get("id") == "word"


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
    [(_SIM, _ALL_ACTIONS), (_BETA, _ALL_ACTIONS)],
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
