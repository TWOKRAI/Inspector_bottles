"""test_recipes_integration.py — Интеграционные smoke-тесты для Phase 5 RecipeManager.

Проверяют сквозные сценарии без GUI и без реальных OS-процессов:
- создание рецепта → set_active → replace_blueprint_fn получает правильный blueprint dict
- загрузка legacy v1-рецепта → автомиграция → .bak файл + version: 2
- duplicate + set_active → get_active возвращает новое имя

Deps: RecipeEngine (framework), RecipeManager, migrate_v1_to_v2, RecipesPresenter, IRecipesView.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.8
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_engine(tmp_path: Path):
    """Создать RecipeEngine с tmp_path и migration support."""
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import RecipeEngine
    from multiprocess_prototype.recipes.migrations.format_v1_to_v2 import (
        is_v1_recipe,
        migrate_v1_to_v2,
    )

    store = TreeStore()
    engine = RecipeEngine(
        store=store,
        recipes_dir=tmp_path,
        migration_fn=migrate_v1_to_v2,
        migration_check_fn=is_v1_recipe,
    )
    return engine


def _make_manager(tmp_path: Path):
    """Создать RecipeManager поверх RecipeEngine с tmp_path."""
    from multiprocess_prototype.recipes.manager import RecipeManager

    engine = _make_engine(tmp_path)
    return RecipeManager(engine=engine, state_proxy=None, logger=None)


def _save_v2_recipe(tmp_path: Path, slug: str, blueprint: dict) -> None:
    """Записать v2-рецепт напрямую в YAML.

    Использует плоский формат (без meta/data обёртки) — аналогично
    RecipesPresenter.on_create(), чтобы presenter.on_set_active мог
    прочитать recipe_data.get("blueprint", {}) напрямую.
    """
    recipe_data = {
        "version": 2,
        "name": slug,
        "description": "smoke test recipe",
        "blueprint": blueprint,
        "active_services": [],
        "display_bindings": [],
    }
    (tmp_path / f"{slug}.yaml").write_text(
        yaml.dump(recipe_data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Test 1: create → activate → replace_blueprint_fn вызвана с blueprint dict
# ---------------------------------------------------------------------------


def test_create_activate_recipe_smoke(tmp_path: Path) -> None:
    """Создать v2-рецепт, set_active → RecipesPresenter вызывает replace_blueprint_fn
    с blueprint dict из YAML.

    Проверяет: сквозной путь RecipeManager → RecipesPresenter → replace_blueprint_fn.
    """
    from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import RecipesPresenter

    # Arrange: создаём рецепт с тестовым blueprint
    blueprint = {
        "processes": [{"process_name": "worker_1", "class": "Worker", "plugins": []}],
        "wires": [],
    }
    slug = "cup_inspection"
    _save_v2_recipe(tmp_path, slug, blueprint)

    manager = _make_manager(tmp_path)

    # Mock replace_blueprint_fn — записывает переданный аргумент
    _captured_blueprint: list[dict] = []

    def _mock_replace(bp: dict) -> dict:
        _captured_blueprint.append(bp)
        return {"success": True, "replaced": ["worker_1"], "rolled_back": False}

    # Mock IRecipesView
    mock_view = MagicMock()
    mock_view.confirm_delete.return_value = True

    presenter = RecipesPresenter(
        recipe_manager=manager,
        view=mock_view,
        replace_blueprint_fn=_mock_replace,
    )

    # Act: активировать рецепт через presenter
    presenter.on_set_active(slug)

    # Assert: replace_blueprint_fn вызвана с blueprint dict
    assert len(_captured_blueprint) == 1, "replace_blueprint_fn должна быть вызвана ровно один раз"
    called_bp = _captured_blueprint[0]
    assert isinstance(called_bp, dict), "replace_blueprint_fn должна получить dict"
    # Blueprint содержит processes (список процессов)
    assert "processes" in called_bp, "blueprint dict должен содержать ключ 'processes'"
    assert len(called_bp["processes"]) == 1, "должен быть один процесс в blueprint"
    assert called_bp["processes"][0]["process_name"] == "worker_1"


# ---------------------------------------------------------------------------
# Test 2: legacy v1-файл → миграция → .bak создан + version: 2 в файле
# ---------------------------------------------------------------------------


def test_migrate_and_load_v1_smoke(tmp_path: Path) -> None:
    """Создать legacy recipe_0.yaml в v1-формате (с topology dict),
    загрузить через RecipeEngine → проверить что .bak создан и файл содержит version: 2.

    Проверяет: migration_fn вызывается при load(), backup создаётся, файл перезаписывается.
    """
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import RecipeEngine
    from multiprocess_prototype.recipes.migrations.format_v1_to_v2 import (
        is_v1_recipe,
        migrate_v1_to_v2,
    )

    # Arrange: v1-формат (data не имеет version → is_v1_recipe вернёт True)
    v1_data = {
        "name": "recipe_0",
        "description": "legacy test recipe",
        "topology": {
            "processes": [{"process_name": "cam_proc", "class": "CameraProcess", "plugins": []}],
            "wires": [],
        },
    }
    v1_file = {
        "meta": {"name": "recipe_0", "version": 1, "description": "legacy"},
        "data": v1_data,
    }
    recipe_file = tmp_path / "recipe_0.yaml"
    recipe_file.write_text(
        yaml.dump(v1_file, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    store = TreeStore()
    engine = RecipeEngine(
        store=store,
        recipes_dir=tmp_path,
        migration_fn=migrate_v1_to_v2,
        migration_check_fn=is_v1_recipe,
    )

    # Act: загружаем рецепт → должна сработать миграция
    engine.load("recipe_0")

    # Assert 1: .bak файл создан рядом с оригинальным
    bak_file = tmp_path / "recipe_0.yaml.bak"
    assert bak_file.exists(), "backup-файл recipe_0.yaml.bak должен быть создан"

    # Assert 2: основной файл перезаписан с version: 2 в meta
    updated = yaml.safe_load(recipe_file.read_text(encoding="utf-8"))
    assert updated is not None, "перезаписанный файл должен быть валидным YAML"
    meta = updated.get("meta", {})
    assert meta.get("version") == 2, f"meta.version должен быть 2, получено: {meta.get('version')}"

    # Assert 3: data в обновлённом файле содержит blueprint (результат migrate_v1_to_v2)
    data = updated.get("data", {})
    # migrate_v1_to_v2 возвращает dict с ключом "blueprint"
    assert "blueprint" in data, "после миграции data должен содержать ключ 'blueprint'"


# ---------------------------------------------------------------------------
# Test 3: duplicate → set_active → get_active возвращает новое имя
# ---------------------------------------------------------------------------


def test_duplicate_and_set_active_smoke(tmp_path: Path) -> None:
    """Создать base_recipe, дублировать в new_recipe, set_active(new_recipe)
    → get_active() == "new_recipe".

    Проверяет: duplicate + set_active работают в связке.
    """

    # Arrange: создать исходный рецепт
    blueprint = {"processes": [], "wires": []}
    slug = "base_recipe"
    _save_v2_recipe(tmp_path, slug, blueprint)

    manager = _make_manager(tmp_path)

    # Act: дублировать и активировать
    dup_result = manager.duplicate("base_recipe", "new_recipe")
    assert dup_result is True, "duplicate должен вернуть True"

    activate_result = manager.set_active("new_recipe")
    assert activate_result is True, "set_active должен вернуть True"

    # Assert: активный рецепт — new_recipe
    active = manager.get_active()
    assert active == "new_recipe", f"get_active() должен быть 'new_recipe', получено: {active!r}"
