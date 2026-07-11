# -*- coding: utf-8 -*-
"""Тесты canonicalize_gui_positions — свёртка дубля gui_positions в одну секцию (Ф4.8).

Покрывает:
  - регистрацию шага в реестре C2 (``migrations.registered_steps``);
  - pure dict→dict контракт (не мутирует вход, идемпотентность);
  - правило «canonical (blueprint.metadata.gui_positions) побеждает при дрейфе»;
  - правило «top-level поднимается в canonical, если canonical пуст»;
  - graceful no-op на не-v3 данных (нет blueprint);
  - эквивалентность загрузки РЕАЛЬНЫХ рецептов (phone_sketch, hikvision_letter_robot)
    через unwrap_recipe (реальный runtime-путь запуска) до/после канонизации;
  - file writer (run_migration) на tmp_path — комментарии/прочие ключи сохранены,
    top-level gui_positions реально удалён с диска.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.recipe.migrations import registered_steps
from multiprocess_prototype.recipes.migrations.canonicalize_gui_positions import (
    DOC_TYPE,
    canonicalize_gui_positions,
    run_migration,
)

_RECIPES_DIR = Path(__file__).resolve().parent.parent
_REAL_RECIPES = ["phone_sketch", "hikvision_letter_robot"]

# ---------------------------------------------------------------------------
# Регистрация в реестре C2
# ---------------------------------------------------------------------------


def test_step_registered_under_doc_type():
    steps = registered_steps(DOC_TYPE)
    assert steps[(1, 2)] is canonicalize_gui_positions


# ---------------------------------------------------------------------------
# Pure dict→dict контракт
# ---------------------------------------------------------------------------


def test_does_not_mutate_input():
    data = {"blueprint": {"metadata": {}}, "gui_positions": {"a": [1.0, 2.0]}}
    original = {"blueprint": {"metadata": {}}, "gui_positions": {"a": [1.0, 2.0]}}
    canonicalize_gui_positions(data)
    assert data == original


def test_noop_without_blueprint_key():
    """Не-v3 данные (нет вложенного blueprint) — возвращаются без изменений."""
    data = {"meta": {"version": 1}, "data": {"cameras": {}}}
    out = canonicalize_gui_positions(data)
    assert out == data


def test_noop_non_dict_input():
    assert canonicalize_gui_positions(None) is None  # type: ignore[arg-type]
    assert canonicalize_gui_positions([1, 2, 3]) == [1, 2, 3]  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Правило "canonical побеждает" / "top-level поднимается, если canonical пуст"
# ---------------------------------------------------------------------------


def test_promotes_top_level_when_canonical_empty():
    """canonical (blueprint.metadata.gui_positions) отсутствует — top-level поднимается."""
    data = {"blueprint": {"metadata": {}}, "gui_positions": {"a": [1.0, 2.0]}}
    out = canonicalize_gui_positions(data)
    assert out["blueprint"]["metadata"]["gui_positions"] == {"a": [1.0, 2.0]}
    assert "gui_positions" not in out


def test_promotes_top_level_when_metadata_missing():
    """blueprint без metadata вовсе — metadata создаётся, top-level поднимается."""
    data = {"blueprint": {}, "gui_positions": {"a": [1.0, 2.0]}}
    out = canonicalize_gui_positions(data)
    assert out["blueprint"]["metadata"]["gui_positions"] == {"a": [1.0, 2.0]}
    assert "gui_positions" not in out


def test_canonical_wins_over_drifted_top_level():
    """canonical непуст — он побеждает БЕЗ слияния, top-level (дрейфнувший) отбрасывается."""
    data = {
        "blueprint": {"metadata": {"gui_positions": {"a": [9.0, 9.0]}}},
        "gui_positions": {"a": [1.0, 2.0]},  # дрейфнувшая копия
    }
    out = canonicalize_gui_positions(data)
    assert out["blueprint"]["metadata"]["gui_positions"] == {"a": [9.0, 9.0]}
    assert "gui_positions" not in out


def test_drops_empty_top_level_when_both_empty():
    data = {"blueprint": {"metadata": {"gui_positions": {}}}, "gui_positions": {}}
    out = canonicalize_gui_positions(data)
    assert "gui_positions" not in out
    assert out["blueprint"]["metadata"]["gui_positions"] == {}


def test_locked_nodes_untouched():
    """Только gui_positions — соседний locked_nodes (без дубля) не трогается."""
    data = {
        "blueprint": {"metadata": {"gui_positions": {"a": [1.0, 2.0]}, "locked_nodes": ["a"]}},
        "gui_positions": {"a": [1.0, 2.0]},
    }
    out = canonicalize_gui_positions(data)
    assert out["blueprint"]["metadata"]["locked_nodes"] == ["a"]


# ---------------------------------------------------------------------------
# Идемпотентность
# ---------------------------------------------------------------------------

_IDEMPOTENCE_SAMPLES: list[dict] = [
    {"blueprint": {"metadata": {}}, "gui_positions": {"a": [1.0, 2.0]}},
    {"blueprint": {"metadata": {"gui_positions": {"a": [9.0, 9.0]}}}, "gui_positions": {"a": [1.0, 2.0]}},
    {"blueprint": {}, "gui_positions": {}},
    {"meta": {}, "data": {}},  # не-v3
    {"blueprint": {"metadata": {"gui_positions": {"x": [0.0, 0.0]}}}},  # уже канонично, дубля нет
]


@pytest.mark.parametrize("sample", _IDEMPOTENCE_SAMPLES)
def test_idempotent(sample: dict):
    once = canonicalize_gui_positions(sample)
    twice = canonicalize_gui_positions(once)
    assert twice == once


# ---------------------------------------------------------------------------
# Эквивалентность загрузки реальных рецептов (через unwrap_recipe — runtime-путь)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_name", _REAL_RECIPES)
def test_real_recipe_has_no_gui_positions_duplicate(recipe_name: str):
    """Sanity (инверсия 2026-07-11): рецепты канонизированы (Ф4.8 apply,
    ``run_migration``/``_migrate_recipe_file`` вызваны на реальных файлах,
    вердикт владельца — одобрено). Top-level дубль ``gui_positions`` больше не
    существует на диске, канонический остаётся только в
    ``blueprint.metadata.gui_positions``. До 2026-07-11 этот тест утверждал
    обратное (дубль есть) — как sanity-проверка для теста эквивалентности
    ниже; теперь эквивалентность проверяется тривиально (raw уже канонично),
    но эта проверка остаётся as regression guard против повторного появления
    дубля."""
    path = _RECIPES_DIR / f"{recipe_name}.yaml"
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    assert "gui_positions" not in raw
    assert "gui_positions" in raw["blueprint"]["metadata"]


@pytest.mark.parametrize("recipe_name", _REAL_RECIPES)
def test_real_recipe_unwrap_equivalent_before_after(recipe_name: str):
    """RecipeEngine/unwrap-путь: канонизация не меняет то, что реально запускает бэкенд."""
    from multiprocess_prototype.backend.launch import unwrap_recipe
    from multiprocess_framework.modules.recipe.detect import is_v3_recipe

    path = _RECIPES_DIR / f"{recipe_name}.yaml"
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    canonicalized = canonicalize_gui_positions(raw)

    # is_v3_recipe (RecipeEngine.load) не меняет вердикт — структура блюпринта цела.
    assert is_v3_recipe(raw) is True
    assert is_v3_recipe(canonicalized) is True

    # unwrap_recipe — то, что реально запускает SystemBuilder — даёт идентичный результат:
    # top-level gui_positions им не читается вовсе (bp = dict(raw["blueprint"])).
    assert unwrap_recipe(raw) == unwrap_recipe(canonicalized)


@pytest.mark.parametrize("recipe_name", _REAL_RECIPES)
def test_real_recipe_live_gui_read_path_unchanged(recipe_name: str):
    """Живой read-путь редактора (metadata.gui_positions) не меняется канонизацией.

    LayoutController.load_topology_from_config читает именно
    ``metadata.get("gui_positions", {})`` — этот путь должен остаться бит-в-бит,
    несмотря на то, что top-level дубль исчезает.
    """
    path = _RECIPES_DIR / f"{recipe_name}.yaml"
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    before = raw["blueprint"]["metadata"]["gui_positions"]
    canonicalized = canonicalize_gui_positions(raw)
    after = canonicalized["blueprint"]["metadata"]["gui_positions"]

    assert after == before
    assert "gui_positions" not in canonicalized


@pytest.mark.parametrize("recipe_name", _REAL_RECIPES)
def test_real_recipe_canonicalization_is_idempotent(recipe_name: str):
    path = _RECIPES_DIR / f"{recipe_name}.yaml"
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    once = canonicalize_gui_positions(raw)
    twice = canonicalize_gui_positions(once)
    assert twice == once


# ---------------------------------------------------------------------------
# File writer (run_migration) — только на tmp_path, реальные рецепты не трогаем
# ---------------------------------------------------------------------------


def _recipe_with_drifted_duplicate() -> str:
    return textwrap.dedent(
        """\
        # Рецепт-заголовок.
        name: demo
        version: 1
        blueprint:
          name: demo
          # --- Камера ---
          processes:
            - process_name: camera_0
              plugins:
                - plugin_name: capture
          wires: []
          metadata:
            gui_positions:
              camera_0.capture: [9.0, 9.0]
            locked_nodes: []
        gui_positions:
          camera_0.capture: [1.0, 2.0]
        """
    )


def test_run_migration_removes_top_level_and_preserves_comments(tmp_path):
    path = tmp_path / "demo.yaml"
    path.write_text(_recipe_with_drifted_duplicate(), encoding="utf-8")

    changed = run_migration(tmp_path)

    assert changed == [path]
    text = path.read_text(encoding="utf-8")
    assert "# Рецепт-заголовок." in text
    assert "# --- Камера ---" in text

    data = yaml.safe_load(text)
    assert "gui_positions" not in data  # top-level дубль удалён
    assert data["blueprint"]["metadata"]["gui_positions"] == {"camera_0.capture": [9.0, 9.0]}  # canonical цел
    assert data["blueprint"]["processes"][0]["process_name"] == "camera_0"  # прочее не тронуто
    assert data["version"] == 1  # версия рецепта НЕ меняется (не про это канонизация)


def test_run_migration_promotes_when_canonical_missing(tmp_path):
    path = tmp_path / "legacy.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            name: legacy
            blueprint:
              processes: []
              wires: []
            gui_positions:
              node_a: [5.0, 6.0]
            """
        ),
        encoding="utf-8",
    )

    changed = run_migration(tmp_path)

    assert changed == [path]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "gui_positions" not in data
    assert data["blueprint"]["metadata"]["gui_positions"] == {"node_a": [5.0, 6.0]}


def test_run_migration_idempotent_second_run_no_changes(tmp_path):
    path = tmp_path / "demo.yaml"
    path.write_text(_recipe_with_drifted_duplicate(), encoding="utf-8")

    run_migration(tmp_path)
    changed_second = run_migration(tmp_path)

    assert changed_second == []  # уже канонично — второй прогон ничего не меняет


def test_run_migration_skips_recipe_without_duplicate(tmp_path):
    path = tmp_path / "clean.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            name: clean
            blueprint:
              processes: []
              wires: []
              metadata:
                gui_positions:
                  node_a: [1.0, 1.0]
            """
        ),
        encoding="utf-8",
    )

    changed = run_migration(tmp_path)
    assert changed == []


def test_run_migration_raises_on_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_migration(tmp_path / "does_not_exist")
