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

import pytest

from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.tests.recipe_pult_support import (
    _EXPECTED_WORD_CONTROL,
    _PROJECT_ROOT,
    _RECIPE_NAMES,
    _CONTROL_PANEL_CLASS,
    _pult_controls_raw,
    _topology_dict,
)


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
# А5
# --------------------------------------------------------------------------- #


def test_pult_controls_identical_in_both_recipes() -> None:
    """А5 (обновлено в 6.7): все контролы ``pult`` (слово, лента, «Домой», «Серво ВКЛ», мониторы) равны в двух рецептах.

    До R4 «Домой»/«Серво ВКЛ» были только в sim; с 6.7 они и в β (драйвер delta_v2) — сравнение полное.
    """
    sim, real = (_pult_controls_raw(name) for name in _RECIPE_NAMES)
    # страж против «пусто == пусто»: без контролов сравнение прошло бы вхолостую
    assert sim, "в letter_robot_sim у pult нет контролов"
    assert real, "в hikvision_letter_robot у pult нет контролов"
    # страж: «Домой»/«Серво ВКЛ» действительно есть в sim, иначе полное равенство не пинит их в β
    assert {"robot_park", "robot_servo"} <= {c.get("target_command") for c in sim}
    assert sim == real
