"""Тесты автора: опасности механизма канонизации proc_dict для сравнения.

В отличие от ``test_protected_conflicts_semantics.py`` (независимые
acceptance-тесты, писались от критериев приёмки без чтения реализации), этот
файл смотрит на конкретный механизм ``_canonicalize_proc_dict_for_comparison``
/ ``_canonicalize_plugin_entry`` и проверяет то, что видно только автору:

- главная опасность задачи — ``proc_dicts`` дальше едут в ``process.create``,
  поэтому канонизация ОБЯЗАНА быть чистой (не мутировать вход);
- вырожденные формы из правил 3 и 4 спецификации (запись без ``config`` /
  ``config`` не dict; элемент списка плагинов, который не dict).
"""

from __future__ import annotations

import copy

from multiprocess_prototype.backend.assembly.planner import (
    FullReplacePlanner,
    _canonicalize_plugin_entry,
    _canonicalize_proc_dict_for_comparison,
    _diverged_paths,
)


def _conflicts(new_proc_dict: dict, live_proc_dict: dict, name: str = "devices") -> list[str]:
    """Прогнать детекцию через ПУБЛИЧНУЮ дорогу планировщика и вернуть вердикт."""
    planner = FullReplacePlanner(
        proc_dicts_fn=lambda desired: {name: new_proc_dict},
        protected_provider=lambda: {name},
        current_provider=lambda: set(),
        protected_config_provider={name: live_proc_dict}.get,
    )
    planner.initialize()
    planner.commands({"has_changes": True}, {"processes": []})
    return planner.last_protected_conflicts


# ---------------------------------------------------------------------------
# Немутирование входа — самая опасная часть задачи: proc_dicts едут дальше
# в process.create, канонизация не имеет права их менять.
# ---------------------------------------------------------------------------


def test_canonicalize_proc_dict_does_not_mutate_input():
    """Каноническая форма — новый dict; исходный proc_dict побитово не тронут."""
    proc_dict = {
        "name": "devices",
        "class": "pkg.GenericProcessApp",
        "config": {
            "plugins": [
                {
                    "plugin_class": "Plugins.hub.device_hub.plugin.DeviceHubPlugin",
                    "plugin_name": "device_hub",
                    "registry_path": "data/devices.yaml",
                    "config": {"registry_path": "data/devices.yaml", "poll_interval_s": 5},
                }
            ]
        },
    }
    snapshot = copy.deepcopy(proc_dict)

    canonical = _canonicalize_proc_dict_for_comparison(proc_dict)

    assert proc_dict == snapshot, "вход не должен измениться после канонизации"
    # и результат действительно другой объект/структура, а не тот же список
    assert canonical is not proc_dict
    assert canonical["config"]["plugins"] is not proc_dict["config"]["plugins"]


def test_detect_protected_conflicts_does_not_mutate_proc_dicts_used_for_create():
    """Опасность из спеки: proc_dicts, прошедшие через _detect_protected_conflicts,
    едут дальше в process.create — детекция конфликтов не должна их менять.
    """
    live_plugin_flat = {
        "plugin_class": "Plugins.hub.device_hub.plugin.DeviceHubPlugin",
        "plugin_name": "device_hub",
        "registry_path": "data/devices.yaml",
    }
    new_plugin_nested = {
        "plugin_class": "Plugins.hub.device_hub.plugin.DeviceHubPlugin",
        "plugin_name": "device_hub",
        "config": {"registry_path": "data/devices.yaml"},
    }
    live = {"name": "devices", "class": "pkg.App", "config": {"plugins": [live_plugin_flat]}}
    new_proc_dicts = {"devices": {"name": "devices", "class": "pkg.App", "config": {"plugins": [new_plugin_nested]}}}
    snapshot = copy.deepcopy(new_proc_dicts)

    planner = FullReplacePlanner(
        proc_dicts_fn=lambda desired: new_proc_dicts,
        protected_provider=lambda: {"devices"},
        current_provider=lambda: set(),
        protected_config_provider={"devices": live}.get,
    )
    assert planner.initialize() is True

    planner.commands({"has_changes": True}, {"processes": []})

    assert new_proc_dicts == snapshot, "proc_dicts, идущие дальше в process.create, не должны мутироваться"
    assert planner.last_protected_conflicts == []  # эквивалентны по смыслу — не конфликт


# ---------------------------------------------------------------------------
# Канон обязан совпадать с рантаймом — это ГЛАВНОЕ свойство после ревью.
#
# Ревью 2026-08-18, блокер 1: первая версия изобрела «сторож противоречия» —
# пару «плоско A + вложенно B» считала неразрешимой и отказывалась канонизировать.
# Неоднозначности в системе нет: PluginOrchestrator._extract_plugin_config —
# единственная граница, за которой рождается ctx.config, — разворачивает вложенный
# config ПОВЕРХ плоского. Значит такая пара означает ровно B, а сторож возвращал
# ложный конфликт на форме, которую ассемблер порождает сам (дефект плагина
# плоско + значение рецепта вложенно).
# ---------------------------------------------------------------------------


def test_canon_config_is_literally_what_the_runtime_extracts():
    """Канон не пересказывает правило рантайма, а берёт его. Своя копия правила
    разошлась бы с ним на первой правке, и сравнение отвечало бы про другую систему.
    """
    from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
        PluginOrchestrator,
    )

    shapes = [
        {"plugin_class": "X", "plugin_name": "y", "category": "hub", "a": 1},
        {"plugin_class": "X", "plugin_name": "y", "config": {"a": 1}},
        {"plugin_class": "X", "plugin_name": "y", "a": 1, "config": {"a": 2, "b": 3}},
        {"plugin_class": "X", "plugin_name": "y", "config": {"category": "hub"}},
    ]
    for entry in shapes:
        assert _canonicalize_plugin_entry(entry)["config"] == PluginOrchestrator._extract_plugin_config(entry)


def test_nested_beats_flat_and_that_is_not_a_conflict():
    """Живой конфиг = B; новый = «плоско A, вложенно B». Рантайм у обоих даёт B,
    значит расхождения НЕТ. Прежняя версия здесь кричала — это и был блокер 1.
    """
    new = {
        "name": "devices",
        "class": "pkg.App",
        "config": {
            "plugins": [
                {"plugin_class": "P", "plugin_name": "hub", "registry_path": "A", "config": {"registry_path": "B"}}
            ]
        },
    }
    live = {
        "name": "devices",
        "class": "pkg.App",
        "config": {"plugins": [{"plugin_class": "P", "plugin_name": "hub", "registry_path": "B"}]},
    }
    assert _conflicts(new, live) == []


def test_meta_key_hidden_in_nested_config_is_a_real_divergence():
    """Мета-поле плоско рантайм ОТБРАСЫВАЕТ, а во вложенном config — оставляет
    параметром. Значит ctx.config действительно разный, и молчать здесь нельзя.
    """
    new = {
        "name": "devices",
        "class": "pkg.App",
        "config": {"plugins": [{"plugin_class": "P", "plugin_name": "hub", "config": {"category": "hub"}}]},
    }
    live = {
        "name": "devices",
        "class": "pkg.App",
        "config": {"plugins": [{"plugin_class": "P", "plugin_name": "hub", "category": "hub"}]},
    }
    assert _conflicts(new, live) == ["devices"]


def test_plugin_class_change_with_identical_params_is_a_conflict():
    """Мета-поля в ctx.config не попадают, но определяют, КАКОЙ плагин грузится:
    канон обязан держать их отдельно, а не растворять в параметрах.
    """
    new = {
        "name": "devices",
        "class": "pkg.App",
        "config": {"plugins": [{"plugin_class": "NEW", "plugin_name": "hub", "a": 1}]},
    }
    live = {
        "name": "devices",
        "class": "pkg.App",
        "config": {"plugins": [{"plugin_class": "OLD", "plugin_name": "hub", "a": 1}]},
    }
    assert _conflicts(new, live) == ["devices"]


def test_non_dict_config_is_ignored_exactly_as_the_runtime_ignores_it():
    """``config`` не-dict рантайм не разворачивает и в параметры не кладёт.
    Сравнение обязано вести себя так же, иначе оно судит о том, чего не будет.
    """
    with_junk = {"plugin_class": "X", "plugin_name": "y", "a": 1, "config": "not-a-dict"}
    without = {"plugin_class": "X", "plugin_name": "y", "a": 1}
    assert _canonicalize_plugin_entry(with_junk) == _canonicalize_plugin_entry(without)


# ---------------------------------------------------------------------------
# Вырожденные формы: элемент списка плагинов не dict; proc_dict без plugins.
# ---------------------------------------------------------------------------


def test_non_dict_plugin_list_element_survives_canonicalization():
    """Не-dict элемент списка не роняет канонизацию и доезжает как есть."""
    proc_dict = {
        "name": "devices",
        "class": "pkg.App",
        "config": {"plugins": ["not-a-dict-entry", {"plugin_name": "hub", "config": {"a": 1}}]},
    }

    canonical = _canonicalize_proc_dict_for_comparison(proc_dict)

    assert canonical["config"]["plugins"][0] == "not-a-dict-entry"
    assert canonical["config"]["plugins"][1] == {"plugin_name": "hub", "config": {"a": 1}}


def test_proc_dict_without_plugins_list_is_compared_verbatim():
    """Нет config / config не dict / plugins не список → proc_dict сравнивается
    дословно. Проверяем РАВЕНСТВО, а не тождество объекта: тождество сторожило бы
    выбор реализации, а не свойство (правило проекта про шпиона за именем API).
    """
    for shape in (
        {"name": "devices", "class": "pkg.App"},
        {"name": "devices", "class": "pkg.App", "config": "not-a-dict"},
        {"name": "devices", "class": "pkg.App", "config": {"plugins": "not-a-list"}},
    ):
        snapshot = copy.deepcopy(shape)
        assert _canonicalize_proc_dict_for_comparison(shape) == snapshot
        assert shape == snapshot


# ---------------------------------------------------------------------------
# Голос: он и назвал третью причину на живом стенде, а тестами покрыт не был
# (находка ревью, неблокер 4).
# ---------------------------------------------------------------------------


def test_voice_names_the_path_inside_a_plugin_not_just_the_list():
    """Спуск по списку. Без него главный случай сворачивался в «config.plugins» —
    оператор узнавал ровно то, что и так знал.
    """
    live = {"config": {"plugins": [{"plugin_name": "hub", "config": {"registry_path": "A"}}]}}
    new = {"config": {"plugins": [{"plugin_name": "hub", "config": {"registry_path": "B"}}]}}

    paths = _diverged_paths(live, new)

    assert paths == ["config.plugins[0].config.registry_path"]


def test_voice_reports_list_length_change():
    """Списки разной длины: назвать длины, а не молчать и не падать по индексу."""
    paths = _diverged_paths({"p": [1, 2]}, {"p": [1]})
    assert paths == ["p (длина 2 против 1)"]


def test_voice_survives_a_self_referencing_config():
    """Якорь yaml ``&r {k: 1, self: *r}`` строит самоссылку. Дословное сравнение
    dict'ов её переживало — значит голос не имеет права ронять ``commands()``
    рекурсией: предохранитель закрывает поверхность, которой раньше не было.
    """
    a: dict = {"k": 1}
    a["self"] = a
    b: dict = {"k": 2}
    b["self"] = b

    paths = _diverged_paths(a, b)

    assert any("k" in p for p in paths)
