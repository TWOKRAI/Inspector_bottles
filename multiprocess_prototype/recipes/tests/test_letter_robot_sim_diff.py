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
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_RECIPES_DIR = Path(__file__).resolve().parents[1]
_BASE_PATH = _RECIPES_DIR / "hikvision_letter_robot.yaml"
_SIM_PATH = _RECIPES_DIR / "letter_robot_sim.yaml"


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
    # Идентичность файла (решение ведущего, см. докстринг): рецепт грузится по имени
    # файла, но ``name``/``description`` внутри обязаны говорить про сим, а не про бой.
    identity_keys = (".name", ".description")
    # Провод, АДРЕСУЮЩИЙ заменённый плагин, — следствие той же замены, а не второе
    # расхождение. Найдено живым стендом 2026-09-21: прототип на сим-рецепте падал
    # валидацией `Wire: источник 'camera_0.hikvision.frame' не найден среди выходов`,
    # потому что провод называет плагин ПО ИМЕНИ, а имя сменилось вместе с блоком.
    # Прежняя буквальная трактовка «ровно один блок» запрещала эту правку и тем самым
    # требовала заведомо нерабочий рецепт.
    wire_source_key = ".blueprint.wires[0].source"
    all_diffs = _diff_paths(base, sim)
    real_diffs = [
        d
        for d in all_diffs
        if not d.startswith(allowed_prefix)
        and d not in identity_keys
        and d != wire_source_key
    ]

    assert real_diffs == [], (
        f"letter_robot_sim.yaml отличается от hikvision_letter_robot.yaml НЕ ТОЛЬКО в "
        f"{allowed_prefix} (критерий 4 требует РОВНО это топологическое расхождение; "
        f"легальны ещё только {identity_keys}): "
        f"лишние расхождения ({len(real_diffs)}): {real_diffs[:20]}"
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

    # Позитивная половина: camera_0.plugins[0] в sim-рецепте ДЕЙСТВИТЕЛЬНО отличается
    # от боевого — иначе выше можно было бы солгать пустым файлом-копией (real_diffs==[]
    # тривиально верно, если sim == base целиком, что провалило бы предыдущий assert
    # разве что при точной копии — здесь фиксируем, что копия НЕ считается допустимым
    # прохождением критерия 4: сим-рецепт обязан ОТЛИЧАТЬСЯ, не просто "не отличаться
    # ничем лишним").
    # Провод обязан адресовать плагин, который в сим-рецепте ДЕЙСТВИТЕЛЬНО есть:
    # иначе рецепт не собирается (воспроизведено на живом стенде).
    sim_plugin_name = sim["blueprint"]["processes"][camera_idx]["plugins"][0]["plugin_name"]
    wire_src = sim["blueprint"]["wires"][0]["source"]
    assert wire_src == f"camera_0.{sim_plugin_name}.frame", (
        f"провод источника = {wire_src!r}, а плагин камеры в сим-рецепте называется "
        f"{sim_plugin_name!r} — провод адресует плагин по имени, рассинхрон роняет "
        f"сборку прототипа на валидации topology"
    )

    sim_camera_plugin0 = sim["blueprint"]["processes"][camera_idx]["plugins"][0]
    base_camera_plugin0 = base_processes[camera_idx]["plugins"][0]
    assert sim_camera_plugin0 != base_camera_plugin0, (
        f"processes[camera_0].plugins[0] в sim-рецепте ИДЕНТИЧЕН боевому "
        f"({sim_camera_plugin0!r}) — letter_robot_sim.yaml не может быть точной копией "
        f"hikvision_letter_robot.yaml, camera_0 обязан стать симулятором"
    )
