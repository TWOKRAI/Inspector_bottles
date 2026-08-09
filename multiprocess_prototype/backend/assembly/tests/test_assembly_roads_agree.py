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
    "case, observability_section, recipe_observability, env_level",
    [
        # Штатный случай прототипа: L1 задан, рецепт молчит.
        ("только L1", {"log_level": "WARNING"}, None, None),
        # L2 оптом.
        ("L1 + defaults рецепта", {"log_level": "WARNING"}, {"defaults": {"log_level": "DEBUG"}}, None),
        # L2 поимённо: у соседа своё, у остальных — оптовое.
        (
            "L1 + per-process",
            {"log_level": "WARNING"},
            {"defaults": {"log_level": "INFO"}, "processes": {"camera_0": {"log_level": "ERROR"}}},
            None,
        ),
        # Короткая форма — ключи прямо в секции.
        ("короткая форма L2", {"log_level": "WARNING"}, {"log_level": "ERROR"}, None),
        # Молчат оба слоя. БЕЗ env этот кейс слеп по построению — см. ниже.
        ("оба слоя молчат", None, None, None),
        ("L1 пустой словарь", {}, {}, None),
        # ГЛАВНЫЙ случай: молчат оба слоя И уровень пришёл из окружения.
        #
        # Ревью итерации 2: без `env_level` предыдущие два кейса не различали
        # исторического расхождения дорог. Причина — `expand_observability({})`
        # поверх ПОЛНОЙ секции менеджеров совпадает с ней значение-в-значение,
        # если ничто не пришло другим путём. Различие появляется ровно тогда,
        # когда другой путь есть: `INSPECTOR_LOG_LEVEL` через
        # `managers_from_log_dir`. Проверено инъекцией: с env матрица ловит
        # безусловное наложение сама, без env — оставалась зелёной.
        ("оба слоя молчат + уровень из окружения", None, None, "ERROR"),
        ("короткая форма L2 + уровень из окружения", {}, {"log_level": "DEBUG"}, "ERROR"),
    ],
)
def test_both_roads_lay_out_observability_identically(
    case, observability_section, recipe_observability, env_level, monkeypatch
) -> None:
    if env_level:
        monkeypatch.setenv("INSPECTOR_LOG_LEVEL", env_level)
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


class TestBothRoadsRefuseAnUnknownProcessName:
    """Task 5.5 (A4): опечатка в ``observability.processes`` громкая на ОБЕИХ дорогах.

    Проверка живёт в ``SystemBlueprint.check()``, который зовут оба сборщика, —
    поэтому паритет здесь не «повторили в двух местах», а «механизм один». Тест
    всё равно проверяет обе: расхождение уже случалось именно на том, что одна
    дорога звала общий код, а вторая шла своим путём (находка ревью 5.13).

    Почему отказ, а не громкая строка: `observability.processes` и список
    процессов лежат в ОДНОМ документе рецепта — несовпадение может быть только
    опечаткой. Секции из `system.yaml` и спутника авторятся отдельно, и там путь
    мягкий (`unknown_refs` в ответе `config.reload`).
    """

    _TYPO = {"defaults": {"log_level": "INFO"}, "processes": {"camera_9": {"log_level": "DEBUG"}}}

    def test_generic_road_refuses(self) -> None:
        from multiprocess_framework.modules.app_module.builder import BlueprintError

        with pytest.raises(BlueprintError) as exc:
            _both_roads({"log_level": "WARNING"}, self._TYPO)
        text = str(exc.value)
        assert "camera_9" in text
        # Сообщение обязано быть действующим: назвать доступные имена, иначе
        # оператор знает только «не так», но не «как».
        assert "camera_0" in text and "processor" in text, text

    def test_applied_road_refuses(self) -> None:
        from multiprocess_prototype.backend.assembly.assembler import BlueprintInvalid

        bp = copy.deepcopy(_BLUEPRINT)
        bp["observability"] = self._TYPO
        with pytest.raises(BlueprintInvalid) as exc:
            BlueprintAssembler(
                observability_section={"log_level": "WARNING"},
                log_dir="logs/x",
                telemetry_dict=None,
                recipe_path="/rec/demo.yaml",
                app_config_path="/cfg/system.yaml",
            ).assemble(bp)
        assert "camera_9" in str(exc.value)

    def test_orchestrator_is_a_legitimate_address(self) -> None:
        """Капкан 5.13: оркестратор адресуем секцией, но в `processes` рецепта его нет.

        Забудь мы его в известных именах — собственная фича 5.13 (`ProcessManager`
        получает свою секцию) отвергалась бы как опечатка на ОБЕИХ дорогах.
        """
        section = {"processes": {"ProcessManager": {"log_level": "DEBUG"}}}
        generic, applied = _both_roads({"log_level": "WARNING"}, section)
        assert generic and applied

    def test_known_names_pass_on_both_roads(self) -> None:
        """Вторая половина пары: без неё зелена реализация «отказывать всегда»."""
        section = {"processes": {"camera_0": {"log_level": "DEBUG"}, "processor": {"log_level": "ERROR"}}}
        generic, applied = _both_roads({"log_level": "WARNING"}, section)
        assert set(generic) == set(applied)

    def test_short_form_without_processes_is_not_judged(self) -> None:
        generic, applied = _both_roads({"log_level": "WARNING"}, {"log_level": "DEBUG"})
        assert generic and applied
