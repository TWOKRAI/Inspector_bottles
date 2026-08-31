"""Независимые приёмочные тесты детекции расхождения конфига protected-процессов.

Пишутся ОТ acceptance-критериев (см. задачу тестера), без чтения тела
``FullReplacePlanner._detect_protected_conflicts``. Источник истины —
конструктор/докстринги ``planner.py`` (сигнатуры провайдеров) и форма
proc_dict, которая реально ходит в системе: параметр плагина встречается в
ДВУХ написаниях одного и того же — плоско (фундамент) и вложенно в
``"config"`` (рецепты). Детектор обязан считать их эквивалентными по
значению и при этом не терять реальные расхождения.

Все четыре провайдера (``proc_dicts_fn``, ``protected_provider``,
``current_provider``, ``protected_config_provider``) — простые лямбды/dict.get,
никакой реальной топологии или живых процессов не требуется.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.backend.assembly.planner import FullReplacePlanner


# ---------------------------------------------------------------------------
# Хелперы построения proc_dict / plugin-записи
# ---------------------------------------------------------------------------


def _plugin(
    *,
    registry_path: str | None = None,
    flat: bool = True,
    extra: dict | None = None,
    plugin_name: str = "device_hub",
) -> dict:
    """Одна запись плагина в форме, реально ходящей в системе.

    flat=True  → параметр пишется прямо в записи (стиль фундамента).
    flat=False → параметр пишется во вложенном ``config`` (стиль рецептов).
    """
    entry: dict = {
        "plugin_class": "Plugins.hub.device_hub.plugin.DeviceHubPlugin",
        "plugin_name": plugin_name,
        "category": "hub",
    }
    if flat:
        if registry_path is not None:
            entry["registry_path"] = registry_path
        if extra:
            entry.update(extra)
    else:
        cfg: dict = {}
        if registry_path is not None:
            cfg["registry_path"] = registry_path
        if extra:
            cfg.update(extra)
        entry["config"] = cfg
    return entry


def _proc(
    name: str,
    *,
    klass: str = "multiprocess_prototype.generic_process_app.GenericProcessApp",
    plugins: list[dict] | None = None,
) -> dict:
    """proc_dict процесса — форма из задачи тестера (name/class/config.plugins)."""
    return {
        "name": name,
        "class": klass,
        "config": {"plugins": plugins or []},
    }


def _run(proc_dicts: dict[str, dict], protected_names: set, config_provider) -> list[str]:
    """Прогнать planner.commands(...) и вернуть last_protected_conflicts.

    config_provider — либо None (детекция выключена, A8), либо callable(name)->dict|None.
    """
    planner = FullReplacePlanner(
        proc_dicts_fn=lambda desired: proc_dicts,
        protected_provider=lambda: set(protected_names),
        current_provider=lambda: set(),
        protected_config_provider=config_provider,
    )
    assert planner.initialize() is True
    planner.commands({"has_changes": True}, {"processes": []})
    return planner.last_protected_conflicts


# ---------------------------------------------------------------------------
# A1 / A2 — эквивалентность плоской и вложенной записи одного и того же значения
# ---------------------------------------------------------------------------


def test_flat_live_vs_nested_new_same_value_no_conflict():
    """A1: живой конфиг плоско, новый вложенно, значение одинаковое → без конфликта."""
    live = _proc("devices", plugins=[_plugin(registry_path="data/devices.yaml", flat=True)])
    new = _proc("devices", plugins=[_plugin(registry_path="data/devices.yaml", flat=False)])

    conflicts = _run({"devices": new}, {"devices"}, {"devices": live}.get)

    assert conflicts == []


def test_nested_live_vs_flat_new_same_value_no_conflict():
    """A2: обратная сторона — живой вложенно, новый плоско, значение одинаковое → без конфликта."""
    live = _proc("devices", plugins=[_plugin(registry_path="data/devices.yaml", flat=False)])
    new = _proc("devices", plugins=[_plugin(registry_path="data/devices.yaml", flat=True)])

    conflicts = _run({"devices": new}, {"devices"}, {"devices": live}.get)

    assert conflicts == []


# ---------------------------------------------------------------------------
# A3 — реальное изменение значения обязано быть найдено в ЛЮБОМ написании
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flat_live, flat_new",
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
    ids=["flat-flat", "flat-nested", "nested-flat", "nested-nested"],
)
def test_value_change_is_conflict_regardless_of_representation(flat_live, flat_new):
    """A3: registry_path реально изменился (devices.yaml → other.yaml) → конфликт ЕСТЬ."""
    live = _proc("devices", plugins=[_plugin(registry_path="data/devices.yaml", flat=flat_live)])
    new = _proc("devices", plugins=[_plugin(registry_path="data/other.yaml", flat=flat_new)])

    conflicts = _run({"devices": new}, {"devices"}, {"devices": live}.get)

    assert conflicts == ["devices"]


# ---------------------------------------------------------------------------
# A4 — вложенный ключ, которого нет в плоской записи, нельзя съедать
# ---------------------------------------------------------------------------


def test_nested_extra_key_absent_in_flat_is_conflict():
    """A4: во вложенном config есть ключ (poll_interval_s), которого нет в плоской записи → конфликт."""
    live = _proc("devices", plugins=[_plugin(registry_path="data/devices.yaml", flat=True)])
    new_plugin = _plugin(registry_path="data/devices.yaml", flat=False, extra={"poll_interval_s": 5})
    new = _proc("devices", plugins=[new_plugin])

    conflicts = _run({"devices": new}, {"devices"}, {"devices": live}.get)

    assert conflicts == ["devices"]


# ---------------------------------------------------------------------------
# A5 — расхождение вне плагинов (детектор не должен видеть только plugins)
# ---------------------------------------------------------------------------


def test_process_level_class_change_outside_plugins_is_conflict():
    """A5: ключ "class" процесса разошёлся (плагины идентичны) → конфликт ЕСТЬ."""
    same_plugin = _plugin(registry_path="data/devices.yaml", flat=True)
    live = _proc("devices", klass="pkg.OldGenericProcessApp", plugins=[dict(same_plugin)])
    new = _proc("devices", klass="pkg.NewGenericProcessApp", plugins=[dict(same_plugin)])

    conflicts = _run({"devices": new}, {"devices"}, {"devices": live}.get)

    assert conflicts == ["devices"]


# ---------------------------------------------------------------------------
# A6 — внутреннее противоречие плоского и вложенного ключа в ОДНОЙ записи
# ---------------------------------------------------------------------------


def test_flat_and_nested_contradiction_within_single_entry_is_conflict():
    """A6: в НОВОЙ записи плагина одновременно registry_path="A" (плоско) и
    config.registry_path="B" (вложенно) — молча выбрать одно из двух нельзя,
    конфликт ЕСТЬ независимо от того, что говорит живой конфиг.
    """
    contradictory_new_plugin = {
        "plugin_class": "Plugins.hub.device_hub.plugin.DeviceHubPlugin",
        "plugin_name": "device_hub",
        "category": "hub",
        "registry_path": "A",
        "config": {"registry_path": "B"},
    }
    new = _proc("devices", plugins=[contradictory_new_plugin])
    # живой конфиг совпадает с ОДНОЙ из двух половин — противоречие всё равно
    # не должно молча разрешаться в её пользу.
    live = _proc("devices", plugins=[_plugin(registry_path="A", flat=True)])

    conflicts = _run({"devices": new}, {"devices"}, {"devices": live}.get)

    assert conflicts == ["devices"]


# ---------------------------------------------------------------------------
# A7 — имя вне живых protected не попадает в конфликты
# ---------------------------------------------------------------------------


def test_name_absent_from_protected_provider_is_excluded():
    """A7: живой конфиг для "devices" расходится с новым, но protected_provider()
    его не называет живым protected → в конфликты не попадает.
    """
    live = _proc("devices", plugins=[_plugin(registry_path="data/devices.yaml", flat=True)])
    new = _proc("devices", plugins=[_plugin(registry_path="data/other.yaml", flat=True)])

    conflicts = _run({"devices": new}, set(), {"devices": live}.get)

    assert conflicts == []


# ---------------------------------------------------------------------------
# A8 — protected_config_provider=None выключает детекцию целиком
# ---------------------------------------------------------------------------


def test_config_provider_none_disables_detection_entirely():
    """A8: protected_config_provider=None → детекция выключена, список пуст,
    даже когда расхождение (если бы его искали) было бы найдено.
    """
    new = _proc("devices", plugins=[_plugin(registry_path="data/other.yaml", flat=True)])

    conflicts = _run({"devices": new}, {"devices"}, None)

    assert conflicts == []


# ---------------------------------------------------------------------------
# A9 — отсутствие живого конфига для имени не конфликт (сравнивать не с чем)
# ---------------------------------------------------------------------------


def test_missing_live_config_for_name_is_not_a_conflict():
    """A9: protected_config_provider("devices") -> None (живого конфига нет) →
    не конфликт, сравнивать не с чем.
    """
    new = _proc("devices", plugins=[_plugin(registry_path="data/other.yaml", flat=True)])

    conflicts = _run({"devices": new}, {"devices"}, {}.get)

    assert conflicts == []
