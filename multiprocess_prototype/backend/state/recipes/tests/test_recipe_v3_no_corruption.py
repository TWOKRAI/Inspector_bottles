"""Regression-тесты: v3-рецепты НЕ портятся при load() (fix recipe-v3-engine-decouple).

Корневой баг: generic RecipeEngine.load() для v3-blueprint-рецепта (top-level
``{name, version, blueprint}`` без envelope ``data``) видел ``data={}`` и отсутствие
``meta.version`` → считал legacy → переписывал файл миграцией пустого ``data``,
впрыскивая ``meta:{migrated_from_v1}`` + ``data:{пустой blueprint}`` и затирая
``blueprint`` + комментарии. Это ломало активацию (Recipe.from_dict → ValidationError)
и сохранение.

Фикс: prototype-wrapper RecipeEngine.load() короткозамыкает v3 — только пометка
active, без migrate/replay/перезаписи. Legacy config-snapshot (envelope data/meta)
по-прежнему мигрируется.
"""

from __future__ import annotations

import textwrap

import yaml

from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_prototype.backend.state.recipes import RecipeEngine

_V3_RECIPE = textwrap.dedent(
    """\
    # Комментарий рецепта — должен сохраниться.
    name: demo_v3
    version: 3
    description: "Тестовый v3-рецепт"

    blueprint:
      name: demo_v3
      processes:
        - process_name: camera_0
          plugins:
            - plugin_class: pkg.Cam
              plugin_name: capture
              category: source
              camera_id: 0
      wires: []
      displays: []
    """
)


def test_v3_recipe_not_modified_on_load(tmp_path):
    """load() v3-рецепта не меняет файл (байт-в-байт) и не создаёт .bak."""
    recipe_path = tmp_path / "demo_v3.yaml"
    recipe_path.write_text(_V3_RECIPE, encoding="utf-8")
    original = recipe_path.read_text(encoding="utf-8")

    engine = RecipeEngine(TreeStore(), tmp_path)
    deltas = engine.load("demo_v3")

    assert recipe_path.read_text(encoding="utf-8") == original  # файл не тронут
    assert not (tmp_path / "demo_v3.yaml.bak").exists()  # нет backup от миграции
    assert "# Комментарий рецепта" in recipe_path.read_text(encoding="utf-8")
    assert deltas == []  # v3 не реплеит config в TreeStore
    assert engine.get_active() == "demo_v3"  # active помечен


def test_v3_recipe_readable_after_load(tmp_path):
    """После load() v3-файл остаётся валидным top-level v3 (не превращается в meta/data)."""
    recipe_path = tmp_path / "demo_v3.yaml"
    recipe_path.write_text(_V3_RECIPE, encoding="utf-8")

    engine = RecipeEngine(TreeStore(), tmp_path)
    engine.load("demo_v3")

    data = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    assert "blueprint" in data
    assert "data" not in data  # не впрыснут legacy-envelope
    assert "meta" not in data
    assert data["version"] == 3


def test_v3_set_active_idempotent_no_corruption(tmp_path):
    """Повторная активация v3-рецепта не накапливает порчу (стабильно после N load)."""
    recipe_path = tmp_path / "demo_v3.yaml"
    recipe_path.write_text(_V3_RECIPE, encoding="utf-8")
    original = recipe_path.read_text(encoding="utf-8")

    engine = RecipeEngine(TreeStore(), tmp_path)
    for _ in range(3):
        engine.load("demo_v3")

    assert recipe_path.read_text(encoding="utf-8") == original
