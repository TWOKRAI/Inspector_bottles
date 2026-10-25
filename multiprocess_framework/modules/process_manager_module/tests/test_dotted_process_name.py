"""Точка в ``process_name`` -> ошибка ``check_structure()`` и ``check()`` (plans/topology-port-join.md, C25.1).

Слепые приёмочные тесты (написаны до реализации): A1-A5. A0 - у developer (существующий тест).
Ожидаемые значения - литералы плана (подстроки текста ошибки, число рецептов 22).

Реестр плагинов - как в ``test_modeless_collector_check.py``: свои фейковые плагины, снимок/восстановление
``PluginRegistry``. Тест A5 собирает боевые рецепты и использует настоящий реестр (без очистки).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

# Литералы плана (A1/A2/A3).
_REASON = "точка в имени процесса"
_ADR = "ADR-PMM-017"

# tests/<file> -> parents[4] == корень проекта (Inspector_bottles).
PROJECT_ROOT = Path(__file__).resolve().parents[4]
RECIPES_DIR = PROJECT_ROOT / "multiprocess_prototype" / "recipes"
RECIPE_COUNT = 22  # литерал плана, robot_demo включён


@pytest.fixture
def _isolated_registry():
    """Снимок/восстановление глобального PluginRegistry; внутри теста реестр пуст."""
    snapshot = PluginRegistry.snapshot()
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(snapshot)


def _register_noports() -> None:
    """Плагин без портов ``noports``."""
    cls = type(
        "_NoPorts",
        (ProcessModulePlugin,),
        {
            "name": "noports",
            "category": "processing",
            "inputs": [],
            "outputs": [],
            "configure": lambda self, ctx: None,
            "start": lambda self, ctx: None,
        },
    )
    PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)


def _blueprint(*proc_names: str) -> SystemBlueprint:
    procs = [{"process_name": n, "plugins": [{"plugin_name": "noports", "plugin_class": ""}]} for n in proc_names]
    return SystemBlueprint.model_validate({"name": "dotted_name", "processes": procs, "wires": []})


def _dotted(errors: list[str]) -> list[str]:
    return [e for e in errors if _REASON in e]


# ---------------------------------------------------------------------------
# A1. draw.a - ровно одна ошибка в check_structure() и в check()
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_isolated_registry")
def test_a1_check_structure_reports_dotted_name_exactly_once() -> None:
    _register_noports()
    bp = _blueprint("draw.a")

    hits = [e for e in bp.check_structure() if "'draw.a'" in e and _REASON in e]

    assert len(hits) == 1, hits
    assert _ADR in hits[0]


@pytest.mark.usefixtures("_isolated_registry")
def test_a1_check_reports_dotted_name_exactly_once() -> None:
    _register_noports()
    bp = _blueprint("draw.a")

    hits = [e for e in bp.check() if "'draw.a'" in e and _REASON in e]

    assert len(hits) == 1, hits
    assert _ADR in hits[0]


# ---------------------------------------------------------------------------
# A2. draw + draw.a: ошибка только про draw.a
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_isolated_registry")
def test_a2_only_the_dotted_process_is_reported_not_its_prefix() -> None:
    _register_noports()
    bp = _blueprint("draw", "draw.a")

    errors = bp.check_structure()
    dotted = _dotted(errors)

    assert len(dotted) == 1, dotted
    assert dotted[0].startswith("Процесс 'draw.a':"), dotted[0]
    assert not [e for e in errors if e.startswith("Процесс 'draw':")], errors


# ---------------------------------------------------------------------------
# A3. имя без точки - ошибки нет
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_isolated_registry")
def test_a3_name_without_dot_has_no_dotted_error_in_check_structure() -> None:
    _register_noports()
    bp = _blueprint("draw_a")

    assert _dotted(bp.check_structure()) == []


@pytest.mark.usefixtures("_isolated_registry")
def test_a3_name_without_dot_has_no_dotted_error_in_check() -> None:
    _register_noports()
    bp = _blueprint("draw_a")

    assert _dotted(bp.check()) == []


# ---------------------------------------------------------------------------
# A4. check_structure() при пустом реестре - та же ошибка
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_isolated_registry")
def test_a4_check_structure_reports_dotted_name_with_empty_registry() -> None:
    # Реестр очищен фикстурой; плагин НЕ регистрируется.
    assert PluginRegistry.names() == []  # реестр действительно пуст
    bp = _blueprint("draw.a")

    hits = [e for e in bp.check_structure() if "'draw.a'" in e and _REASON in e]

    assert len(hits) == 1, hits
    assert _ADR in hits[0]


# ---------------------------------------------------------------------------
# A5. боевые рецепты: сборка не бросает, имён процессов с точкой нет
# ---------------------------------------------------------------------------

ALL_RECIPES = sorted(p.stem for p in RECIPES_DIR.glob("*.yaml"))


def test_a5_recipe_set_has_the_literal_count_and_robot_demo() -> None:
    """Страж «ноль наблюдений»: параметризация видит ровно 22 рецепта, robot_demo включён."""
    assert len(ALL_RECIPES) == RECIPE_COUNT, ALL_RECIPES
    assert "robot_demo" in ALL_RECIPES


@pytest.mark.parametrize("recipe", ALL_RECIPES)
def test_a5_built_recipe_has_no_dotted_process_name(recipe: str) -> None:
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    launcher = SystemBuilder.from_manifest(app, recipe).build()  # не должна бросать

    names = [name for name, _proc in launcher._processes]
    assert names, f"{recipe}: сборка вернула ноль процессов"
    assert [n for n in names if "." in n] == []
