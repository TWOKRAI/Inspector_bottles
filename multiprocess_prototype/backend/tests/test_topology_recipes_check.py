"""Слепые приёмочные тесты Task 5.9a, часть B: рецепты собираются, ключ проходит по процессу.

Контракт (plans/transport-single-policy/phase-5.md, Task 5.9a, acceptance «(tester)»):

* каждый ``backend/topology/*.yaml`` (кроме ``TEMPLATE*``; ``archive/`` и ``tests/`` —
  подкаталоги, в ``glob("*.yaml")`` не попадают) проходит ТОТ ЖЕ путь, что запуск
  (``launch.py``): yaml -> ``load_topology_dict`` -> ``normalize_blueprint`` ->
  ``BlueprintAssembler.assemble`` без ``BlueprintInvalid``, и ``check() == []``;
* в собранном ``multi_camera.yaml`` у процесса ``compositor`` ``collector.mode == "fanin"``
  (без явного collector провода вывели бы join с ОДНИМ элементом ``inputs`` — ADR-PMM-017);
* из копии ``inspection_basic.yaml`` убраны ВСЕ провода с target
  ``processor.<любой плагин>.frame`` -> ``check()`` называет ``processor.color_mask.frame``
  (один провод не годится: доступность считается по имени ключа на уровне процесса);
* вход узла 0 процесса без провода -> ровно одна ошибка на этот адрес.

Тесты написаны ДО реализации и без доступа к ней. Сегодня красные: два рецепта
(``inspection_basic``, ``multi_camera``) и тесты, которым нужна их сборка. Остальные
рецепты собираются уже сейчас — их тесты зелёные и охраняют от регрессии.

Файл лежит в тестах прототипа, а не фреймворка: он читает рецепты прототипа и
плагины ``Plugins/`` — обратный импорт во фреймворк запрещён слоями.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

# backend/tests/<file> → parents[3] == корень проекта (Inspector_bottles).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY_DIR = PROJECT_ROOT / "multiprocess_prototype" / "backend" / "topology"

#: Рецепты под стражей: все ``*.yaml`` каталога, кроме шаблона. Идентификатор параметра — имя файла.
RECIPE_FILES: list[Path] = sorted(p for p in TOPOLOGY_DIR.glob("*.yaml") if not p.name.startswith("TEMPLATE"))

_PROCESSOR_FRAME_TARGET = re.compile(r"processor\.[^.]+\.frame")


@pytest.fixture
def plugins_discovered() -> None:
    """Те же плагины, что видит запуск: ``discovery.plugin_paths`` боевого system.yaml.

    Проверка на ``color_mask`` — страж «ноль наблюдений»: с пустым реестром ``check()``
    молча пропускает плагины (``entry is None -> continue``) и возвращает ``[]``.
    """
    from multiprocess_framework.modules.app_module import discover

    discover(plugin_paths=[str(PROJECT_ROOT / "Plugins"), str(PROJECT_ROOT / "Services")], service_paths=[])
    assert PluginRegistry.get("color_mask") is not None, "реестр пуст: check() ничего бы не проверил"


def _system_config() -> Any:
    from multiprocess_prototype.backend.config.schemas import load_system_config

    return load_system_config()


def _blueprint_dict(path: Path) -> dict:
    """yaml -> normalized blueprint dict — как ``SystemBuilder.build()`` до ``assemble``."""
    from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
    from multiprocess_prototype.backend.launch import load_topology_dict

    return normalize_blueprint(load_topology_dict(path), _system_config())


def _assemble(path: Path) -> dict[str, dict[str, Any]]:
    """Тот же ``BlueprintAssembler.assemble``, что на старте (``launch.py``, секция L1 сырая)."""
    from multiprocess_prototype.backend.assembly import BlueprintAssembler

    sys_config = _system_config()
    assembler = BlueprintAssembler(
        observability_section=sys_config.observability.model_dump(exclude_unset=True),
        log_dir=sys_config.system.log_dir or "logs",
        telemetry_dict=None,
        recipe_path=str(path),
        app_config_path="",
    )
    return assembler.assemble(_blueprint_dict(path))


def _check(path: Path) -> list[str]:
    """``check()`` на том же чертеже, что видит ``assemble`` (после вывода collector'ов)."""
    topology = SystemBlueprint.model_validate(_blueprint_dict(path))
    topology.infer_missing_collectors()
    return topology.check()


# --------------------------------------------------------------------------- набор рецептов


def test_recipe_set_is_not_empty_and_contains_both_known_broken_recipes() -> None:
    """Страж «ноль наблюдений»: параметризация не опустела и видит оба рецепта задачи."""
    names = {p.name for p in RECIPE_FILES}
    assert {"inspection_basic.yaml", "multi_camera.yaml", "inspection_full.yaml", "base.yaml"} <= names, names
    assert not any(n.startswith("TEMPLATE") for n in names), names


# --------------------------------------------------------------------------- каждый рецепт


@pytest.mark.parametrize("recipe", RECIPE_FILES, ids=lambda p: p.name)
def test_recipe_assembles_without_blueprint_invalid(recipe: Path, plugins_discovered: None) -> None:
    from multiprocess_prototype.backend.assembly import BlueprintInvalid

    try:
        proc_dicts = _assemble(recipe)
    except BlueprintInvalid as exc:
        pytest.fail(f"{recipe.name}: BlueprintInvalid:\n  " + "\n  ".join(exc.errors))
    assert proc_dicts, f"{recipe.name}: assemble вернул пустой набор процессов"


@pytest.mark.parametrize("recipe", RECIPE_FILES, ids=lambda p: p.name)
def test_recipe_check_is_empty(recipe: Path, plugins_discovered: None) -> None:
    errors = _check(recipe)
    assert errors == [], f"{recipe.name}: check() вернул ошибки:\n  " + "\n  ".join(errors)


# --------------------------------------------------------------------------- multi_camera: fan-in


def test_multi_camera_compositor_collector_mode_is_fanin(plugins_discovered: None) -> None:
    """Без явного ``collector: {mode: fanin}`` провода вывели бы ``join`` с одним ``inputs``."""
    proc_dicts = _assemble(TOPOLOGY_DIR / "multi_camera.yaml")
    assert "compositor" in proc_dicts, sorted(proc_dicts)
    assert proc_dicts["compositor"]["config"]["collector"]["mode"] == "fanin", proc_dicts["compositor"]["config"].get(
        "collector"
    )


# --------------------------------------------------------------------------- inspection_basic: провода


def test_inspection_basic_without_processor_frame_wires_fails_naming_color_mask(
    tmp_path: Path, plugins_discovered: None
) -> None:
    """Из копии убраны ВСЕ провода ``-> processor.<плагин>.frame``; вывод называет ``processor.color_mask.frame``.

    Сначала доказываем, что у рецепта такие провода БЫЛИ: сегодня секции ``wires:`` нет,
    и без этого шага тест был бы зелёным вхолостую (удалять нечего, ошибка есть и так).
    """
    from multiprocess_prototype.backend.assembly import BlueprintInvalid

    raw = yaml.safe_load((TOPOLOGY_DIR / "inspection_basic.yaml").read_text(encoding="utf-8"))
    wires = raw.get("wires") or []
    to_remove = [w for w in wires if _PROCESSOR_FRAME_TARGET.fullmatch(str(w.get("target", "")))]
    assert len(to_remove) >= 1, "в inspection_basic.yaml нет проводов на processor.<плагин>.frame — удалять нечего"

    raw["wires"] = [w for w in wires if w not in to_remove]
    copy_path = tmp_path / "inspection_basic_no_processor_frame_wires.yaml"
    copy_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(BlueprintInvalid) as exc_info:
        _assemble(copy_path)
    joined = "\n".join(exc_info.value.errors)
    assert "processor.color_mask.frame" in joined, joined


# --------------------------------------------------------------------------- узел 0 без провода


def test_node_zero_without_wire_gives_exactly_one_error_for_that_address(plugins_discovered: None) -> None:
    """Процесс ``solo``: color_mask (вход ``frame`` обязателен) -> mask_to_frame (вход ``mask`` даёт color_mask).

    Провода нет ни у кого. Вход узла 0 — единственный непокрытый: ровно одна ошибка в
    ``check()``, не две (ни от цепочки, ни от цикла обязательных входов одновременно).
    """
    topology = SystemBlueprint.model_validate(
        {
            "name": "node_zero",
            "processes": [
                {
                    "process_name": "solo",
                    "plugins": [
                        {"plugin_name": "color_mask", "plugin_class": ""},
                        {"plugin_name": "mask_to_frame", "plugin_class": ""},
                    ],
                }
            ],
            "wires": [],
        }
    )
    errors = topology.check()
    assert len(errors) == 1, errors
    assert "color_mask" in errors[0] and "frame" in errors[0], errors[0]
