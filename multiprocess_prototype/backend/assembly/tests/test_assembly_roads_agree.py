# -*- coding: utf-8 -*-
"""Страж: две дороги сборки раскладывают наблюдаемость ОДИНАКОВО (приёмка A8).

Дорог две и они останутся двумя — прикладной ``BlueprintAssembler`` несёт
app-специфику (per-category defaults, telemetry), generic ``assemble_proc_dicts``
её не знает. Одинаковой обязана быть именно раскладка слоёв наблюдаемости: она —
общий контракт, а не частность приложения.

**Почему файл здесь, а не во фреймворке.** Тест импортирует ОБЕ дороги, а
прикладная лежит в ``multiprocess_prototype``. Слои импортов запрещают
фреймворку знать про прототип, поэтому сверка живёт на нижнем слое —
в тестах прототипа, и попадает в гейт (`pytest -q`).

**Что этот файл ловит.** Ревью Task 5.13 нашло, что приёмка A8 («обе копии
раскладывают слои одинаково») была заявлена доказанной pytest'ом, а теста не
существовало — при живом расхождении: generic-дорога проверяла молчание слоёв,
прикладная накладывала безусловно, и у процесса с молчащими слоями секция
``managers`` (уже собранная ``managers_from_log_dir``) затиралась голыми
дефолтами L0 — вместе с уровнем из ``INSPECTOR_LOG_LEVEL``. Расхождение было
латентным ровно потому, что в прототипе ``system.yaml`` всегда несёт секцию
``observability``, а значит слои никогда не молчат.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.app_module.builder import assemble_proc_dicts
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
    OVERRIDE_CONFIG_KEY,
    RECIPE_PATH_CONFIG_KEY,
)
from multiprocess_prototype.backend.assembly.assembler import BlueprintAssembler

_BLUEPRINT: Dict[str, Any] = {
    "name": "roads",
    "processes": [
        {"process_name": "camera_0", "process_class": "some.module.CameraApp", "plugins": []},
        {"process_name": "processor", "process_class": "some.module.ProcessorApp", "plugins": []},
    ],
    "wires": [],
}

#: Ключи наблюдаемости в ``proc_dict["config"]`` — сверяются поимённо.
_CONFIG_KEYS = (APP_CONFIG_KEY, OVERRIDE_CONFIG_KEY, RECIPE_PATH_CONFIG_KEY, "observability_config_path")


def _both_roads(observability_section, recipe_observability):
    """Один и тот же вход через обе дороги → ``(generic, прикладная)``."""
    bp = copy.deepcopy(_BLUEPRINT)
    if recipe_observability is not None:
        bp["observability"] = recipe_observability

    generic = assemble_proc_dicts(
        copy.deepcopy(bp),
        observability_section=observability_section,
        log_dir="logs/x",
        app_config_path="/cfg/system.yaml",
        recipe_path="/rec/demo.yaml",
    )
    applied = BlueprintAssembler(
        observability_section=observability_section,
        log_dir="logs/x",
        telemetry_dict=None,
        recipe_path="/rec/demo.yaml",
        app_config_path="/cfg/system.yaml",
    ).assemble(copy.deepcopy(bp))
    return generic, applied


def _observability_view(proc_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Только наблюдаемость: managers + адресные ключи config.

    Остальное различается ЗАКОННО (app-специфика прикладной дороги), и сверять
    proc_dict целиком значило бы получить страж, который краснеет на постороннем
    и потому будет отключён.
    """
    cfg = proc_dict.get("config") or {}
    return {
        "managers": proc_dict.get("managers", "<нет ключа>"),
        **{k: cfg.get(k, "<нет ключа>") for k in _CONFIG_KEYS},
    }


@pytest.mark.parametrize(
    "case, observability_section, recipe_observability",
    [
        # Штатный случай прототипа: L1 задан, рецепт молчит.
        ("только L1", {"log_level": "WARNING"}, None),
        # L2 оптом.
        ("L1 + defaults рецепта", {"log_level": "WARNING"}, {"defaults": {"log_level": "DEBUG"}}),
        # L2 поимённо: у соседа своё, у остальных — оптовое.
        (
            "L1 + per-process",
            {"log_level": "WARNING"},
            {"defaults": {"log_level": "INFO"}, "processes": {"camera_0": {"log_level": "ERROR"}}},
        ),
        # Короткая форма — ключи прямо в секции.
        ("короткая форма L2", {"log_level": "WARNING"}, {"log_level": "ERROR"}),
        # ГЛАВНЫЙ случай: молчат ОБА слоя. Здесь дороги и расходились.
        ("оба слоя молчат", None, None),
        ("L1 пустой словарь", {}, {}),
    ],
)
def test_both_roads_lay_out_observability_identically(case, observability_section, recipe_observability) -> None:
    generic, applied = _both_roads(observability_section, recipe_observability)

    assert set(generic) == set(applied), f"[{case}] дороги собрали разный состав процессов"
    for name in sorted(generic):
        assert _observability_view(generic[name]) == _observability_view(applied[name]), (
            f"[{case}] раскладка наблюдаемости разошлась у процесса {name!r}"
        )


def test_silent_layers_do_not_clobber_level_from_environment(monkeypatch) -> None:
    """Литерал ожидания, а не сверка дорог между собой.

    Сверка «дорога == дорога» согласна с любым ответом, включая «обе затирают
    уровень дефолтами L0». Поэтому здесь записано, ЧТО именно должно быть.

    Литерал выбран по ЦЕНЕ нарушения, а не по форме. Первая редакция этого теста
    утверждала «ключа ``managers`` нет вовсе» — и упала, потому что к моменту
    раскладки слоёв секция уже собрана ``managers_from_log_dir`` (каталог логов,
    пути файлов, уровень из ``INSPECTOR_LOG_LEVEL``). Наблюдаемая цена наложения
    пустых слоёв — уровень из окружения молча возвращается к дефолту L0 ``INFO``.
    """
    monkeypatch.setenv("INSPECTOR_LOG_LEVEL", "ERROR")
    generic, applied = _both_roads(None, None)
    for road_name, road in (("generic", generic), ("прикладная", applied)):
        for name, proc_dict in road.items():
            level = proc_dict["managers"]["logger"]["default_level"]
            assert level == "ERROR", f"{road_name}/{name}: молчащие слои затёрли уровень из окружения, стало {level!r}"


def test_declared_layer_reaches_managers_on_either_road() -> None:
    """Вторая половина пары: непустой слой обязан доехать до менеджеров.

    Без неё тест выше был бы зелёным и у реализации «никогда ничего не
    накладывать» — то есть страж стерёг бы отсутствие механизма.
    """
    generic, applied = _both_roads({"log_level": "ERROR"}, None)
    for road_name, road in (("generic", generic), ("прикладная", applied)):
        for name, proc_dict in road.items():
            level = proc_dict["managers"]["logger"]["default_level"]
            assert level == "ERROR", f"{road_name}/{name}: L1 не доехал, уровень {level!r}"
