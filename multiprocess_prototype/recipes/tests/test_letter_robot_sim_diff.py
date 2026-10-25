# -*- coding: utf-8 -*-
"""Приёмочный RED-тест (Task 1.2 плана line-sim, критерий 4) для НОВОГО рецепта
``multiprocess_prototype/recipes/letter_robot_sim.yaml`` — сим-вариант боевого
``hikvision_letter_robot.yaml``.

Независимый тестер, БЕЗ реализации. Контракт — дословно из DESIGN брифа lead'а:
"сим-вариант ... отличается РОВНО блоком ``processes[camera_0].plugins[0]``".

Каталог ``multiprocess_prototype/recipes/tests/`` УЖЕ существует (с ``__init__.py``) —
новый файл сюда, ничего заводить не пришлось.

ТРЕНИЕ, СНЯТОЕ ВЕДУЩИМ (2026-09-21). Тестер прочёл "отличается РОВНО одним блоком"
буквально — как запрет расхождений во ВСЁМ дереве, включая ``name``/``description``, и
честно назвал это риском ложного красного. Риск подтвердился: рецепт резолвится ПО ИМЕНИ
ФАЙЛА (``recipe_engine.py:190`` — ``self._recipes_dir / f"{name}.yaml"``), внутреннее поле
``name:`` на загрузку не влияет, но участвует в сравнении активного рецепта
(``recipe_engine.py:329``). Оставить внутри ``letter_robot_sim.yaml`` строку
``name: hikvision_letter_robot`` — значит завести два разных файла с одной идентичностью.
Поэтому ``name`` и ``description`` — ЛЕГАЛЬНЫЕ расхождения (идентичность файла), а "ровно
один блок" из плана относится к ТОПОЛОГИИ: ``version``, все процессы, провода и все прочие
ключи обязаны совпадать, единственное топологическое расхождение — источник ``camera_0``.

C-24 (2026-10-25). Сравнение сырого YAML краснело 46 расхождениями после пересохранения
сим-рецепта GUI-редактором (``efc2612c3``): редактор дописал пустые ``extras``,
``restart_policy``, ``src_dtype``/``tgt_dtype``, top-level ``gui_positions: {}`` и перенёс
``name``/``description`` блюпринта в ``blueprint.metadata``. Топология при этом не менялась.
Поэтому блюпринт сравнивается в каноническом виде — через ``SystemBlueprint``, как его читает
бэкенд, — а раскладка редактора (``blueprint.metadata``, top-level ``gui_positions``,
ADR-RCP-004) вне сравнения. Намеренные расхождения — литералом ``_EXPECTED_DIFFS``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint

_RECIPES_DIR = Path(__file__).resolve().parents[1]
_BASE_PATH = _RECIPES_DIR / "hikvision_letter_robot.yaml"
_SIM_PATH = _RECIPES_DIR / "letter_robot_sim.yaml"

# Раскладка редактора, не топология: канон позиций — blueprint.metadata, top-level
# gui_positions — дубль без уникальных данных (ADR-RCP-004). Весь blueprint.metadata вне
# сравнения: у SystemBlueprint нет поля metadata, бэкенд (model_validate) его не видит.
_LAYOUT_TOP_KEYS = ("gui_positions",)
_LAYOUT_BLUEPRINT_KEYS = ("metadata",)

# Все намеренные расхождения вне блока camera_0.plugins[0], литералом. Причины — в тесте.
_EXPECTED_DIFFS = [
    ".blueprint.wires[0].source",
    ".description",
    ".devices[0].params.robot_params",
    ".devices[0].protocol",
    ".devices[0].transport.host",
    ".devices[0].transport.port",
    ".name",
]


def _canonical(recipe: dict[str, Any]) -> dict[str, Any]:
    """Рецепт без раскладки редактора; блюпринт — в виде ``SystemBlueprint``.

    Пустые значения, которые дописывает редактор, совпадают с умолчаниями схемы и после
    ``model_dump`` неотличимы от отсутствующих ключей. Ключи блюпринта вне схемы
    (``displays``) ``model_dump`` отбрасывает — они сравниваются сырыми.

    Предел (ревью C-24): ``model_dump`` теряет ``model_fields_set``, а явный typed-ключ
    (``chain_targets``, ``source_target_fps``, ``collector``, ``io_peek``) побеждает одноимённый
    в ``extras`` только при явной записи. Дрейф «тот же ключ в общем ``extras`` + явный ключ в
    одном файле» тест не видит; сегодня ``extras`` обоих рецептов пусты.
    """
    out = {k: v for k, v in recipe.items() if k not in _LAYOUT_TOP_KEYS}
    raw_bp = recipe.get("blueprint", {})
    bp = SystemBlueprint.model_validate(raw_bp).model_dump(mode="json")
    for key, value in raw_bp.items():
        if key not in bp and key not in _LAYOUT_BLUEPRINT_KEYS:
            bp[key] = value
    out["blueprint"] = bp
    return out


def _diff_paths(a: Any, b: Any, path: str = "") -> list[str]:
    """Собрать список путей, где ``a`` и ``b`` расходятся (dict/list/скаляр рекурсивно)."""
    if isinstance(a, dict) and isinstance(b, dict):
        diffs: list[str] = []
        for key in sorted(set(a) | set(b), key=str):
            if key not in a or key not in b:
                diffs.append(f"{path}.{key}")
                continue
            diffs.extend(_diff_paths(a[key], b[key], f"{path}.{key}"))
        return diffs
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}[len={len(a)} vs {len(b)}]"]
        diffs = []
        for i, (x, y) in enumerate(zip(a, b)):
            diffs.extend(_diff_paths(x, y, f"{path}[{i}]"))
        return diffs
    if a != b:
        return [path or "<root>"]
    return []


def test_sim_recipe_differs_only_in_camera_block() -> None:
    """Пин критерия 4: единственное расхождение с боевым рецептом —
    ``blueprint.processes[<camera_0>].plugins[0]``.

    Провал сегодня: ``letter_robot_sim.yaml`` отсутствует — AssertionError с явным
    сообщением (не skip, не FileNotFoundError необработанный).
    """
    assert _BASE_PATH.is_file(), f"боевой рецепт-эталон отсутствует: {_BASE_PATH}"
    assert _SIM_PATH.is_file(), (
        f"{_SIM_PATH} отсутствует — критерий 4 требует новый рецепт "
        f"multiprocess_prototype/recipes/letter_robot_sim.yaml (сим-вариант "
        f"hikvision_letter_robot.yaml с заменой источника camera_0 на симулятор)"
    )

    base = yaml.safe_load(_BASE_PATH.read_text(encoding="utf-8"))
    sim = yaml.safe_load(_SIM_PATH.read_text(encoding="utf-8"))
    assert isinstance(base, dict) and isinstance(sim, dict), (
        f"один из рецептов не распарсился в dict: base={type(base)}, sim={type(sim)}"
    )

    base_processes = base.get("blueprint", {}).get("processes", [])
    camera_idx = next(
        (i for i, p in enumerate(base_processes) if isinstance(p, dict) and p.get("process_name") == "camera_0"),
        None,
    )
    assert camera_idx is not None, f"process_name='camera_0' не найден в {_BASE_PATH} — эталон сломан?"

    allowed_prefix = f".blueprint.processes[{camera_idx}].plugins[0]"
    # Ниже — причины каждого пути из _EXPECTED_DIFFS.
    # Идентичность файла (решение ведущего, см. докстринг): рецепт грузится по имени
    # файла, но ``name``/``description`` внутри обязаны говорить про сим, а не про бой.
    # Провод, АДРЕСУЮЩИЙ заменённый плагин, — следствие той же замены, а не второе
    # расхождение. Найдено живым стендом 2026-09-21: прототип на сим-рецепте падал
    # валидацией `Wire: источник 'camera_0.hikvision.frame' не найден среди выходов`,
    # потому что провод называет плагин ПО ИМЕНИ, а имя сменилось вместе с блоком.
    # Прежняя буквальная трактовка «ровно один блок» запрещала эту правку и тем самым
    # требовала заведомо нерабочий рецепт.
    # Адрес робота — второе следствие «сим вместо железа» (найдено при подготовке стенда
    # Task 1.3, 2026-09-21): upsert рецепта при активации ПЕРЕЗАПИСЫВАЕТ transport в
    # data/devices.yaml (`DeviceManager.upsert`, merge поверх), так что копия боевого
    # адреса вела прототип на сим-рецепте к настоящему роботу 192.168.1.7:502.
    # Протокол и параметры сим-робота — третье и четвёртое следствие «сим вместо железа» (T3.7):
    # сим линии работает по v2, боевой робот — по v1 до Ф4; кольцо забора сима шире умолчания.
    # Значения закреплены литералами в test_sim_recipe_points_robot_at_sim_not_hardware.
    all_diffs = _diff_paths(_canonical(base), _canonical(sim))
    other_diffs = sorted(d for d in all_diffs if not d.startswith(allowed_prefix))
    extra = [d for d in other_diffs if d not in _EXPECTED_DIFFS]
    missing = [d for d in _EXPECTED_DIFFS if d not in other_diffs]

    assert other_diffs == _EXPECTED_DIFFS, (
        f"letter_robot_sim.yaml отличается от hikvision_letter_robot.yaml не так, как "
        f"задумано (критерий 4: топологически — только {allowed_prefix}; блюпринт "
        f"сравнивается в каноническом виде SystemBlueprint, раскладка редактора вне "
        f"сравнения): лишние ({len(extra)}): {extra[:20]}; пропавшие намеренные: {missing}"
    )

    # Идентичность НЕ просто разрешена — она обязана быть переписана: файл-копия с
    # чужим ``name`` внутри и есть тот самый "второй боевой рецепт", который план
    # запрещает заводить.
    assert sim.get("name") == "letter_robot_sim", (
        f"name внутри letter_robot_sim.yaml = {sim.get('name')!r}; рецепт резолвится по имени "
        f"файла, но поле name участвует в сравнении активного рецепта "
        f"(recipe_engine.py:329) — оно обязано быть 'letter_robot_sim', иначе сим-рецепт "
        f"выдаёт себя за боевой"
    )

    # Позитивная половина: camera_0 в сим-рецепте ДЕЙСТВИТЕЛЬНО заменён — литералы имён
    # плагина ниже (точная копия боевого рецепта их не пройдёт).
    # Провод обязан адресовать плагин, который в сим-рецепте ДЕЙСТВИТЕЛЬНО есть:
    # иначе рецепт не собирается (воспроизведено на живом стенде).
    sim_plugin_name = sim["blueprint"]["processes"][camera_idx]["plugins"][0]["plugin_name"]
    # Намеренная замена источника — литералом: бой читает Hikvision, сим — поток line_sim.
    assert base_processes[camera_idx]["plugins"][0]["plugin_name"] == "hikvision"
    assert sim_plugin_name == "camera_service"
    wire_src = sim["blueprint"]["wires"][0]["source"]
    assert wire_src == f"camera_0.{sim_plugin_name}.frame", (
        f"провод источника = {wire_src!r}, а плагин камеры в сим-рецепте называется "
        f"{sim_plugin_name!r} — провод адресует плагин по имени, рассинхрон роняет "
        f"сборку прототипа на валидации topology"
    )


def test_sim_recipe_points_robot_at_sim_not_hardware() -> None:
    """robot_main сим-рецепта адресует сим-робот apps/line_sim, а не боевой робот."""
    sim = yaml.safe_load(_SIM_PATH.read_text(encoding="utf-8"))
    robot = next(d for d in sim["devices"] if d["id"] == "robot_main")
    assert robot["transport"]["host"] == "127.0.0.1"
    assert robot["transport"]["port"] == 5021
    # T3.7: сим-робот линии — протокол v2 и кольцо забора 600 мм; боевой эталон остаётся на v1 без robot_params
    assert robot["protocol"] == "delta_v2"
    assert robot["params"]["robot_params"] == {"P_ZONE_MAX": 6000}
    base = yaml.safe_load(_BASE_PATH.read_text(encoding="utf-8"))
    base_robot = next(d for d in base["devices"] if d["id"] == "robot_main")
    assert base_robot["protocol"] == "delta_universal3"
    assert "robot_params" not in (base_robot.get("params") or {})
